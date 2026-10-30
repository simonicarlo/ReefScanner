import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation } from "@tanstack/react-query";
import { api } from "../lib/api";
import {
  useClasses,
  useEvents,
  useJob,
  useJobs,
  useProject,
  useThresholdAnalysis,
} from "../lib/queries";
import type { EventFilters, Job, ReefEvent, Verdict } from "../lib/types";
import { basename, duration, percent, score, timecode } from "../lib/format";
import { VERDICT_INFO } from "../lib/verdicts";
import { BboxOverlay } from "../components/BboxOverlay";
import { PageHeader } from "../components/PageHeader";
import { SegmentedControl } from "../components/SegmentedControl";
import { ThresholdPanel } from "../components/ThresholdPanel";
import { Button, Empty, ErrorNote, Notice, Panel, Spinner, Tag } from "../components/ui";
import styles from "./JobDetail.module.css";

const PAGE = 120;

export function JobDetail() {
  const { jobId } = useParams();
  const id = Number(jobId);

  const [filters, setFilters] = useState<EventFilters>({ limit: PAGE, offset: 0 });
  const { data: job } = useJob(id);
  const { data: page, isLoading, error } = useEvents(id, filters);
  const { data: classes } = useClasses(id);
  const { data: thresholds } = useThresholdAnalysis(id);
  const { data: project } = useProject(job?.project_id ?? 0);
  const writePackage = useMutation({ mutationFn: () => api.writePackage(id) });

  const patch = (next: Partial<EventFilters>) =>
    setFilters((prev) => ({ ...prev, ...next, offset: 0 }));

  const reviewed = page ? page.n_labeled : 0;
  const totalEvents = page?.total ?? 0;
  const unsure = page ? reviewed - page.n_tp - page.n_fp : 0;

  return (
    <div className={styles.page}>
      <PageHeader
        back={job ? { to: `/projects/${job.project_id}`, label: project?.name ?? "Project" } : undefined}
        title={`${job?.source ? "Import" : "Run"} #${id}`}
        subtitle={
          job &&
          `${job.events_found} event${job.events_found === 1 ? "" : "s"} across ${
            job.videos_done
          } video${job.videos_done === 1 ? "" : "s"}`
        }
        actions={
          <>
            {(["coco", "yolo"] as const).map((format) => (
              <a key={format} href={api.exportUrl(id, format)} download className={styles.link}>
                Export {format.toUpperCase()}
              </a>
            ))}
            <Button onClick={() => writePackage.mutate()} disabled={writePackage.isPending}>
              {writePackage.isPending ? "Writing…" : "Write Camtrap DP package"}
            </Button>
          </>
        }
      />

      {writePackage.data && (
        <Notice tone="green">
          Package written to <span className={styles.path}>{writePackage.data.path}</span> (
          {writePackage.data.observations} observations, {writePackage.data.media} media
          files). The folder is the package: copy it to share it.
        </Notice>
      )}
      <ErrorNote error={writePackage.error} />

      {project?.deployment.timestamp_issues && (
        <Notice tone="orange">
          Some videos had no recorded start time, so their times were guessed from the
          files' modification dates and may be off. The package marks this
          deployment's timestamps as having issues.
        </Notice>
      )}

      {/* Review progress: the one number that says how much work is left. */}
      {page && page.total > 0 && (
        <Panel>
          <div className={styles.progress}>
            <div className={styles.progressBar}>
              <div className={styles.progressLabel}>
                Reviewed {reviewed} of {totalEvents}
              </div>
              <div className={styles.bar}>
                <i style={{ width: `${(page.n_tp / totalEvents) * 100}%`, background: "var(--green)" }} />
                <i style={{ width: `${(page.n_fp / totalEvents) * 100}%`, background: "var(--red)" }} />
                <i style={{ width: `${(unsure / totalEvents) * 100}%`, background: "var(--orange)" }} />
              </div>
            </div>
            <dl className={styles.stats}>
              <Stat label="Confirmed" value={page.n_tp} color="var(--green)" />
              <Stat label="Rejected" value={page.n_fp} color="var(--red)" />
              {unsure > 0 && <Stat label="Unsure" value={unsure} color="var(--orange)" />}
              <Stat label="Left" value={totalEvents - reviewed} />
              {reviewed > 0 && <Stat label="False positives" value={percent(page.n_fp / reviewed)} />}
            </dl>
          </div>
        </Panel>
      )}

      {job && <ThresholdPanel jobId={id} projectId={job.project_id} />}

      <div className={styles.filters}>
        <FilterGroup
          label="Review state"
          options={[
            { label: "All", value: undefined },
            { label: "To review", value: false },
            { label: "Reviewed", value: true },
          ]}
          active={filters.labeled}
          onPick={(labeled) => patch({ labeled, verdict: undefined })}
        />

        <FilterGroup
          label="Verdict"
          options={[
            { label: "Any verdict", value: undefined },
            ...(Object.keys(VERDICT_INFO) as Verdict[]).map((v) => ({
              label: VERDICT_INFO[v].label,
              value: v,
            })),
          ]}
          active={filters.verdict}
          onPick={(verdict) => patch({ verdict, labeled: undefined })}
        />

        {!!classes?.length && (
          <FilterGroup
            label="Class"
            options={[
              { label: "All classes", value: undefined },
              ...classes.map((c) => ({ label: c, value: c })),
            ]}
            active={filters.detected_class}
            onPick={(detected_class) => patch({ detected_class })}
          />
        )}

        <label className={styles.slider}>
          <span>Minimum score</span>
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
          />
          <span className={styles.num}>{(filters.min_confidence ?? 0).toFixed(2)}</span>
          {(() => {
            const at = filters.min_confidence ?? 0;
            // The last sweep point at or below the slider describes what this
            // position would keep; below every point, nothing is filtered out.
            const point = [...(thresholds?.points ?? [])]
              .reverse()
              .find((p) => p.threshold <= at);
            if (!point || at === 0) return null;
            return (
              <span className={styles.keeps}>
                Keeps {point.kept},{" "}
                <span className={point.confirmed_lost > 0 ? styles.lost : undefined}>
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
          <div className={styles.grid}>
            {page.items.map((event) => (
              <EventCard key={event.id} event={event} jobId={id} />
            ))}
          </div>

          {page.total > page.items.length && (
            <div className={styles.pager}>
              <Button
                size="sm"
                disabled={filters.offset === 0}
                onClick={() =>
                  setFilters((f) => ({ ...f, offset: Math.max(0, (f.offset ?? 0) - PAGE) }))
                }
              >
                Previous
              </Button>
              <span className={styles.num}>
                {(filters.offset ?? 0) + 1}–{(filters.offset ?? 0) + page.items.length} of{" "}
                {page.total}
              </span>
              <Button
                size="sm"
                disabled={(filters.offset ?? 0) + PAGE >= page.total}
                onClick={() => setFilters((f) => ({ ...f, offset: (f.offset ?? 0) + PAGE }))}
              >
                Next
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
  const withEvents = (siblings ?? []).filter((j) => j.id !== jobId && j.events_found > 0);

  if (filtered) {
    return <Empty title="No events match">Try relaxing the filters above.</Empty>;
  }

  return (
    <Empty title="This run found nothing">
      <p>
        No detections passed the confidence threshold. Lowering it on the project
        page surfaces weaker detections, at the cost of more to review.
      </p>
      {withEvents.length > 0 && (
        <p>
          Looking for earlier results?{" "}
          {withEvents.map((j, i) => (
            <span key={j.id}>
              {i > 0 && ", "}
              <Link to={`/jobs/${j.id}`} className={styles.inlineLink}>
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

function Stat({ label, value, color }: { label: string; value: number | string; color?: string }) {
  return (
    <div className={styles.stat}>
      <dt>
        {color && <i className={styles.statDot} style={{ background: color }} />}
        {label}
      </dt>
      <dd>{value}</dd>
    </div>
  );
}

/** A segmented control over filter values that aren't strings (undefined, booleans). */
function FilterGroup<T>({
  label,
  options,
  active,
  onPick,
}: {
  label: string;
  options: { label: string; value: T }[];
  active: T;
  onPick: (value: T) => void;
}) {
  const index = Math.max(
    0,
    options.findIndex((o) => o.value === active),
  );
  return (
    <SegmentedControl
      label={label}
      options={options.map((o, i) => ({ value: String(i), label: o.label }))}
      value={String(index)}
      onChange={(i) => onPick(options[Number(i)].value)}
    />
  );
}

function EventCard({ event, jobId }: { event: ReefEvent; jobId: number }) {
  const verdict = event.review?.verdict;
  return (
    <Link to={`/jobs/${jobId}/events/${encodeURIComponent(event.id)}`} className={styles.card}>
      <div className={styles.thumb}>
        {/* The clean frame with the box drawn over it. Stretched to the card
            rather than cropped, so the box stays on the animal. */}
        <img src={event.frame_url} alt="" loading="lazy" />
        <BboxOverlay
          bbox={event.review?.bbox ?? event.bbox}
          color={verdict ? VERDICT_INFO[verdict].mark : undefined}
          compact
        />
        {verdict && (
          <Tag tone={VERDICT_INFO[verdict].tone} className={styles.verdictTag}>
            {VERDICT_INFO[verdict].short}
          </Tag>
        )}
        <span className={styles.timecode}>{timecode(event.start_seconds)}</span>
      </div>

      <div className={styles.cardBody}>
        <div className={styles.cardTitle} title={event.source_video}>
          {basename(event.source_video)}
        </div>
        <div className={styles.cardMeta}>
          <span>{duration(event.duration_seconds)}</span>
          <span>Score {score(event.confidence)}</span>
        </div>
        {event.review?.scientific_name && (
          <div className={styles.species}>{event.review.scientific_name}</div>
        )}
      </div>
    </Link>
  );
}
