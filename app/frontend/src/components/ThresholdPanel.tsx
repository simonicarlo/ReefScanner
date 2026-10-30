import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { keys, useProject, useThresholdAnalysis } from "../lib/queries";
import { Button, ErrorNote, Notice, Panel, cx } from "./ui";
import styles from "./ThresholdPanel.module.css";

/**
 * What confidence should this project use?
 *
 * Every number here is simulated from events that were actually emitted and
 * labeled, so it says nothing about what the detector missed below the scan
 * threshold. The wording reflects that — "of what this scan found" is not
 * hedging, it is the honest scope of the claim.
 */
export function ThresholdPanel({ jobId, projectId }: { jobId: number; projectId: number }) {
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
      <Panel title="Confidence threshold">
        <p className={styles.text}>
          Review a few events and this will tell you what confidence threshold to use,
          measured on your footage rather than a benchmark.
        </p>
      </Panel>
    );
  }

  const current = project?.config?.ml_confidence_threshold;
  const alreadyApplied = data.recommended !== null && current === data.recommended;

  return (
    <Panel
      title="Confidence threshold"
      aside={
        <>
          From {data.confirmed} confirmed, {data.rejected} rejected
          {data.undecided > 0 && `, ${data.undecided} undecided`}
          {data.unscored > 0 && `, ${data.unscored} unscored`}
        </>
      }
    >
      <div className={styles.pick}>
        {data.recommended !== null ? (
          <>
            <div>
              <div className={styles.caption}>Recommended</div>
              <div className={styles.value}>{data.recommended.toFixed(2)}</div>
            </div>
            <p className={styles.text}>{data.recommendation}</p>
            <Button
              variant="primary"
              onClick={() => apply.mutate(data.recommended as number)}
              disabled={apply.isPending || !project || alreadyApplied}
            >
              {alreadyApplied ? "Applied" : "Apply to project"}
            </Button>
          </>
        ) : (
          <p className={styles.text}>{data.recommendation}</p>
        )}
      </div>

      <ErrorNote error={apply.error} />

      {!data.reliable && data.points.length > 0 && (
        <Notice tone="orange">
          Only {data.confirmed + data.rejected} labeled detection
          {data.confirmed + data.rejected === 1 ? "" : "s"}, so treat this as a hint
          rather than a measurement. Review more to firm it up.
        </Notice>
      )}

      {data.points.length > 0 && (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Threshold</th>
                <th>To review</th>
                <th>Real</th>
                <th>Junk</th>
                <th>Animals lost</th>
                <th>Precision</th>
              </tr>
            </thead>
            <tbody>
              {data.points.map((point) => (
                <tr
                  key={point.threshold}
                  className={point.threshold === data.recommended ? styles.picked : undefined}
                >
                  <td>{point.threshold.toFixed(2)}</td>
                  <td>{point.kept}</td>
                  <td>{point.confirmed_kept}</td>
                  <td className={styles.dim}>{point.rejected_kept}</td>
                  <td className={cx(point.confirmed_lost > 0 && styles.lost)}>
                    {point.confirmed_lost}
                  </td>
                  <td>{(point.precision * 100).toFixed(0)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className={styles.footnote}>
            Simulated from detections this scan emitted at confidence{" "}
            {data.scan_threshold?.toFixed(2) ?? "—"}. It cannot show animals the detector
            missed below that line.
          </p>
        </div>
      )}
    </Panel>
  );
}
