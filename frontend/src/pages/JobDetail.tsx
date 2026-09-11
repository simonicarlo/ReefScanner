import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { api } from "../lib/api";
import {
  useClasses,
  useEvents,
  useJob,
  useJobs,
  useThresholdAnalysis,
} from "../lib/queries";
import type { EventFilters, Job, ReefEvent, Verdict } from "../lib/types";
import { basename, duration, percent, score, timecode } from "../lib/format";
import { Button, Empty, ErrorNote, Spinner, Tag, cx } from "../components/ui";
import { ThresholdPanel } from "../components/ThresholdPanel";

const PAGE = 120;

const VERDICT_TONE: Record<Verdict, "signal" | "reject" | "hedge"> = {
  TP: "signal",
  FP: "reject",
  unsure: "hedge",
};

export function JobDetail() {
  const { jobId } = useParams();
  const id = Number(jobId);

  const [filters, setFilters] = useState<EventFilters>({ limit: PAGE, offset: 0 });
  const { data: job } = useJob(id);
  const { data: page, isLoading, error } = useEvents(id, filters);
  const { data: classes } = useClasses(id);
  const { data: thresholds } = useThresholdAnalysis(id);

  const importCsv = useMutation({ mutationFn: () => api.importCsv(id) });

  const patch = (next: Partial<EventFilters>) =>
    setFilters((prev) => ({ ...prev, ...next, offset: 0 }));

  const reviewed = page ? page.n_labeled : 0;
  const totalEvents = page?.total ?? 0;

  return (
    <div className="rise space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          {job && (
            <Link to={`/projects/${job.project_id}`} className="legend hover:text-signal">
              ← Project
            </Link>
          )}
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">
            Run #{id}
          </h1>
          {job && (
            <p className="mt-1 text-sm text-faint">
              {job.status} · {job.events_found} event
              {job.events_found === 1 ? "" : "s"} across {job.videos_done} video
              {job.videos_done === 1 ? "" : "s"}
            </p>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={() => importCsv.mutate()}>
            {importCsv.isPending ? "Importing…" : "Import existing CSV"}
          </Button>
          {(["csv", "coco", "yolo"] as const).map((format) => (
            <a key={format} href={api.exportUrl(id, format)} download>
              <Button size="sm" variant="ghost">
                Export {format.toUpperCase()}
              </Button>
            </a>
          ))}
        </div>
      </div>

      {importCsv.data && (
        <div className="rounded-[3px] border border-signal/40 bg-signal/10 px-3 py-2 text-sm text-signal">
          Imported {importCsv.data.imported} event(s) from {importCsv.data.source}
        </div>
      )}
      <ErrorNote error={importCsv.error} />

      {/* Review progress. The one number that says how much work is left. */}
      {page && page.total > 0 && (
        <div className="panel flex flex-wrap items-center gap-x-8 gap-y-3 px-4 py-3">
          <div className="min-w-[12rem] flex-1">
            <div className="legend mb-1.5">
              Reviewed {reviewed} of {totalEvents}
            </div>
            <div className="flex h-1.5 overflow-hidden rounded-full bg-abyss">
              <div
                className="bg-signal transition-[width] duration-500"
                style={{ width: `${(page.n_tp / Math.max(1, totalEvents)) * 100}%` }}
              />
              <div
                className="bg-reject transition-[width] duration-500"
                style={{ width: `${(page.n_fp / Math.max(1, totalEvents)) * 100}%` }}
              />
              <div
                className="bg-hedge transition-[width] duration-500"
                style={{
                  width: `${((reviewed - page.n_tp - page.n_fp) / Math.max(1, totalEvents)) * 100}%`,
                }}
              />
            </div>
          </div>
          <div className="flex gap-6">
            <Stat label="Confirmed" value={page.n_tp} tone="text-signal" />
            <Stat label="Rejected" value={page.n_fp} tone="text-reject" />
            <Stat label="Left" value={totalEvents - reviewed} tone="text-dim" />
            {reviewed > 0 && (
              <Stat
                label="False pos."
                value={percent(page.n_fp / reviewed)}
                tone="text-dim"
              />
            )}
          </div>
        </div>
      )}

      {job && <ThresholdPanel jobId={id} projectId={job.project_id} />}

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2">
        <FilterGroup
          options={[
            { label: "All", value: undefined },
            { label: "To review", value: false },
            { label: "Reviewed", value: true },
          ]}
          active={filters.labeled}
          onPick={(labeled) => patch({ labeled, verdict: undefined })}
        />

        <FilterGroup
          options={[
            { label: "Any verdict", value: undefined },
            { label: "TP", value: "TP" },
            { label: "FP", value: "FP" },
            { label: "Unsure", value: "unsure" },
          ]}
          active={filters.verdict}
          onPick={(verdict) => patch({ verdict: verdict as Verdict, labeled: undefined })}
        />

        {!!classes?.length && (
          <FilterGroup
            options={[
              { label: "All classes", value: undefined },
              ...classes.map((c) => ({ label: c, value: c })),
            ]}
            active={filters.detected_class}
            onPick={(detected_class) => patch({ detected_class: detected_class as string })}
          />
        )}

        <label className="ml-auto flex items-center gap-2">
          <span className="legend">Min confidence</span>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={filters.min_confidence ?? 0}
            onChange={(e) => {
              const v = Number(e.target.value);
              patch({ min_confidence: v === 0 ? undefined : v });
            }}
            className="accent-[var(--color-signal)]"
          />
          <span className="tabular w-8 text-xs text-dim">
            {(filters.min_confidence ?? 0).toFixed(2)}
          </span>
          {(() => {
            const at = filters.min_confidence ?? 0;
            // The last sweep point at or below the slider describes what this
            // position would keep; below every point, nothing is filtered out.
            const point = [...(thresholds?.points ?? [])]
              .reverse()
              .find((p) => p.threshold <= at);
            if (!point || at === 0) return null;
            return (
              <span className="legend">
                keeps {point.kept} ·{" "}
                <span className={point.confirmed_lost > 0 ? "text-reject" : ""}>
                  loses {point.confirmed_lost} confirmed
                </span>
              </span>
            );
          })()}
        </label>
      </div>

      <ErrorNote error={error} />

      {isLoading && !page ? (
        <Spinner label="Loading events" />
      ) : !page?.items.length ? (
        <EmptyGrid jobId={id} job={job} filtered={totalEvents > 0} />
      ) : (
        <>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(230px,1fr))] gap-3">
            {page.items.map((event, i) => (
              <EventCard
                key={event.id}
                event={event}
                jobId={id}
                delay={Math.min(i, 24) * 25}
              />
            ))}
          </div>

          {page.total > page.items.length && (
            <div className="flex items-center justify-center gap-3 pt-2">
              <Button
                size="sm"
                disabled={filters.offset === 0}
                onClick={() =>
                  setFilters((f) => ({
                    ...f,
                    offset: Math.max(0, (f.offset ?? 0) - PAGE),
                  }))
                }
              >
                ← Previous
              </Button>
              <span className="tabular text-xs text-faint">
                {(filters.offset ?? 0) + 1}–
                {(filters.offset ?? 0) + page.items.length} of {page.total}
              </span>
              <Button
                size="sm"
                disabled={(filters.offset ?? 0) + PAGE >= page.total}
                onClick={() =>
                  setFilters((f) => ({ ...f, offset: (f.offset ?? 0) + PAGE }))
                }
              >
                Next →
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function EmptyGrid({
  jobId,
  job,
  filtered,
}: {
  jobId: number;
  job: Job | undefined;
  filtered: boolean;
}) {
  // Other runs of the same project may hold the events someone is looking for
  // — most often the first one, before a setting was changed.
  const { data: siblings } = useJobs(job?.project_id ?? 0);
  const withEvents = (siblings ?? []).filter(
    (j) => j.id !== jobId && j.events_found > 0,
  );

  if (filtered) {
    return <Empty title="No events match">Try relaxing the filters above.</Empty>;
  }

  const skippedEverything = (job?.message ?? "").startsWith("Nothing to do");

  return (
    <Empty title={skippedEverything ? "Nothing was scanned" : "This run found nothing"}>
      <p>
        {skippedEverything
          ? "Every video had already been scanned with these exact settings, so there was nothing to redo. Change a setting on the project page and run again to rescan."
          : "No detections passed the confidence threshold. Lowering it on the project page surfaces weaker detections, at the cost of more to review."}
      </p>
      {withEvents.length > 0 && (
        <p className="mt-3">
          Looking for earlier results?{" "}
          {withEvents.map((j, i) => (
            <span key={j.id}>
              {i > 0 && ", "}
              <Link to={`/jobs/${j.id}`} className="text-signal hover:underline">
                Run #{j.id}
              </Link>{" "}
              has {j.events_found}
            </span>
          ))}
          .
        </p>
      )}
    </Empty>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | string;
  tone: string;
}) {
  return (
    <div>
      <div className="legend">{label}</div>
      <div className={cx("tabular text-lg leading-tight", tone)}>{value}</div>
    </div>
  );
}

function FilterGroup<T>({
  options,
  active,
  onPick,
}: {
  options: { label: string; value: T }[];
  active: T;
  onPick: (value: T) => void;
}) {
  return (
    <div className="flex overflow-hidden rounded-[3px] border border-rule">
      {options.map((option) => (
        <button
          key={String(option.label)}
          type="button"
          onClick={() => onPick(option.value)}
          className={cx(
            "px-2.5 py-1 font-mono text-xs transition-colors",
            active === option.value
              ? "bg-signal/15 text-signal"
              : "text-faint hover:bg-panel-hi hover:text-read",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

function EventCard({
  event,
  jobId,
  delay,
}: {
  event: ReefEvent;
  jobId: number;
  delay: number;
}) {
  return (
    <Link
      to={`/jobs/${jobId}/events/${event.id}`}
      style={{ animationDelay: `${delay}ms` }}
      className="panel rise group overflow-hidden transition-colors hover:border-signal/50"
    >
      <div className="relative aspect-video bg-abyss">
        {event.thumbnail_url ? (
          <img
            src={event.thumbnail_url}
            alt=""
            loading="lazy"
            className="h-full w-full object-cover opacity-90 transition-opacity group-hover:opacity-100"
          />
        ) : (
          <div className="flex h-full items-center justify-center text-xs text-faint">
            no thumbnail
          </div>
        )}

        {event.label && (
          <div className="absolute left-1.5 top-1.5">
            <Tag tone={VERDICT_TONE[event.label.verdict]}>{event.label.verdict}</Tag>
          </div>
        )}

        <div className="absolute bottom-1.5 right-1.5">
          <span className="tabular rounded-[3px] bg-abyss/85 px-1.5 py-0.5 text-[11px] text-read">
            {timecode(event.start_seconds)}
          </span>
        </div>
      </div>

      <div className="space-y-1 p-2.5">
        <div
          className="truncate text-xs text-dim"
          title={event.source_video}
        >
          {basename(event.source_video)}
        </div>
        <div className="flex items-center justify-between gap-2">
          <span className="tabular text-[11px] text-faint">
            {duration(event.duration_seconds)}
          </span>
          <span className="tabular text-[11px] text-faint">
            {event.ml_confidence !== null
              ? `conf ${score(event.ml_confidence)}`
              : `motion ${score(event.motion_score, 0)}`}
          </span>
        </div>
        {event.label?.species && (
          <div className="truncate text-[11px] text-signal">
            {event.label.species}
          </div>
        )}
      </div>
    </Link>
  );
}
