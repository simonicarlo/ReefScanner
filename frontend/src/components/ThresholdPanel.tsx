import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { keys, useProject, useThresholdAnalysis } from "../lib/queries";
import { Button, ErrorNote, cx } from "./ui";

/**
 * What confidence should this project use?
 *
 * Every number here is simulated from events that were actually emitted and
 * labeled, so it says nothing about what the detector missed below the scan
 * threshold. The wording reflects that — "of what this scan found" is not
 * hedging, it is the honest scope of the claim.
 */
export function ThresholdPanel({
  jobId,
  projectId,
}: {
  jobId: number;
  projectId: number;
}) {
  const { data, isLoading } = useThresholdAnalysis(jobId);
  const { data: project } = useProject(projectId);
  const queryClient = useQueryClient();

  const apply = useMutation({
    // PATCH replaces the whole config blob rather than merging into it, so the
    // existing settings must be sent back or applying a threshold would wipe
    // every other tunable on the project.
    mutationFn: (threshold: number) =>
      api.updateProject(projectId, {
        config: { ...(project?.config ?? {}), ml_confidence_threshold: threshold },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: keys.project(projectId) });
    },
  });

  if (isLoading || !data) return null;
  if (data.labeled === 0) {
    return (
      <div className="panel px-4 py-3 text-sm text-faint">
        Review a few events and this will tell you what confidence threshold to
        use — measured on your footage, not a benchmark.
      </div>
    );
  }

  const current = project?.config?.ml_confidence_threshold;
  const alreadyApplied =
    data.recommended !== null && current === data.recommended;

  return (
    <section className="panel p-4">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="text-sm font-medium">Confidence threshold</h2>
        <span className="legend">
          from {data.confirmed} confirmed · {data.rejected} rejected
          {data.undecided > 0 && ` · ${data.undecided} undecided`}
          {data.unscored > 0 && ` · ${data.unscored} unscored`}
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-4">
        {data.recommended !== null ? (
          <>
            <div>
              <div className="legend">Recommended</div>
              <div className="tabular text-2xl leading-tight text-signal">
                {data.recommended.toFixed(2)}
              </div>
            </div>
            <p className="min-w-[14rem] flex-1 text-xs text-dim">
              {data.recommendation}
            </p>
            <Button
              variant="primary"
              size="sm"
              onClick={() => apply.mutate(data.recommended as number)}
              disabled={apply.isPending || !project || alreadyApplied}
            >
              {alreadyApplied ? "Applied" : "Apply to project"}
            </Button>
          </>
        ) : (
          <p className="text-xs text-dim">{data.recommendation}</p>
        )}
      </div>

      <ErrorNote error={apply.error} />

      {!data.reliable && data.points.length > 0 && (
        <p className="mt-3 rounded-[3px] border border-hedge/40 bg-hedge/10 px-2.5 py-1.5 text-xs text-hedge">
          Only {data.confirmed + data.rejected} labeled detection(s) — treat this
          as a hint, not a measurement. Review more to firm it up.
        </p>
      )}

      {data.points.length > 0 && (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[34rem] text-left">
            <thead>
              <tr className="legend">
                <th className="py-1 pr-4 font-normal">Threshold</th>
                <th className="py-1 pr-4 font-normal">To review</th>
                <th className="py-1 pr-4 font-normal">Real</th>
                <th className="py-1 pr-4 font-normal">Junk</th>
                <th className="py-1 pr-4 font-normal">Animals lost</th>
                <th className="py-1 font-normal">Precision</th>
              </tr>
            </thead>
            <tbody className="tabular text-sm">
              {data.points.map((point) => {
                const isPick = point.threshold === data.recommended;
                return (
                  <tr
                    key={point.threshold}
                    className={cx(
                      "border-t border-rule",
                      isPick && "bg-signal/10 text-signal",
                    )}
                  >
                    <td className="py-1.5 pr-4">{point.threshold.toFixed(2)}</td>
                    <td className="py-1.5 pr-4">{point.kept}</td>
                    <td className="py-1.5 pr-4">{point.confirmed_kept}</td>
                    <td className="py-1.5 pr-4 text-faint">{point.rejected_kept}</td>
                    <td
                      className={cx(
                        "py-1.5 pr-4",
                        point.confirmed_lost > 0 && "text-reject",
                      )}
                    >
                      {point.confirmed_lost}
                    </td>
                    <td className="py-1.5">
                      {(point.precision * 100).toFixed(0)}%
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="mt-2 text-xs text-faint">
            Simulated from detections this scan emitted at confidence{" "}
            {data.scan_threshold?.toFixed(2) ?? "—"}. It cannot show animals the
            detector missed below that line.
          </p>
        </div>
      )}
    </section>
  );
}
