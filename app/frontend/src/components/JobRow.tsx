import { Link } from "react-router-dom";
import type { Job } from "../lib/types";
import { percent, shortDate } from "../lib/format";
import { Button, Tag, cx } from "./ui";

const TONE = {
  running: "accent",
  pending: "neutral",
  done: "green",
  failed: "red",
  cancelled: "orange",
} as const;

export function JobRow({
  job,
  onCancel,
  onResume,
}: {
  job: Job;
  onCancel?: (id: number) => void;
  onResume?: (id: number) => void;
}) {
  const live = job.status === "running" || job.status === "pending";
  // A stopped run picks up where it left off, keeping its events whole.
  const resumable = job.status === "cancelled" || job.status === "failed";
  const hasEvents = job.events_found > 0;

  return (
    // The whole row is the click target. It previously wasn't, and a row of
    // readouts with one small link in the corner reads as a status panel
    // rather than something you open — which is exactly how it behaved.
    <div
      className={cx(
        "panel group relative px-4 py-3 transition-colors",
        "hover:border-signal/50 hover:bg-panel-hi/60",
        "focus-within:border-signal/50",
      )}
    >
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        {/* Stretched link: a real anchor for keyboard and middle-click, whose
            ::after covers the row so anywhere is clickable. */}
        <Link
          to={`/jobs/${job.id}`}
          className="tabular text-sm text-read after:absolute after:inset-0 group-hover:text-signal"
        >
          {job.source ? "Import" : "Run"} #{job.id}
        </Link>

        <Tag tone={TONE[job.status]}>
          {job.status}
        </Tag>

        <span className="min-w-0 flex-1 truncate text-sm text-faint">
          {job.message || "—"}
        </span>

        <span className="tabular text-xs text-faint">{shortDate(job.started_at)}</span>

        {/* The event count is what someone is actually looking for, so it gets
            the weight — and says what clicking will do. */}
        <span
          className={cx(
            "flex items-center gap-2",
            hasEvents ? "text-signal" : "text-faint",
          )}
        >
          <span className="tabular text-lg leading-none">{job.events_found}</span>
          <span className="legend !text-current">
            {job.events_found === 1 ? "event" : "events"}
          </span>
        </span>

        {live && onCancel ? (
          // Above the stretched link, or the row would swallow the click.
          <Button
            size="sm"
            variant="danger"
            className="relative z-10"
            onClick={() => onCancel(job.id)}
          >
            Stop
          </Button>
        ) : resumable && onResume ? (
          <Button
            size="sm"
            className="relative z-10"
            onClick={() => onResume(job.id)}
          >
            Resume
          </Button>
        ) : (
          <span
            className={cx(
              "legend flex items-center gap-1 transition-colors",
              hasEvents ? "group-hover:text-signal" : "opacity-40",
            )}
          >
            {hasEvents ? "Review" : "Open"}
            <span aria-hidden className="transition-transform group-hover:translate-x-0.5">
              →
            </span>
          </span>
        )}
      </div>

      {live && (
        <div className="mt-2.5 flex items-center gap-3">
          <div className="relative h-1 flex-1 overflow-hidden rounded-full bg-abyss">
            <div
              className="h-full bg-signal transition-[width] duration-500 ease-out"
              style={{ width: `${Math.max(2, job.progress * 100)}%` }}
            />
            {/* The sweep says "still alive" even when a long video keeps the
                percentage still for a while. */}
            <div className="sweeping absolute inset-0 overflow-hidden" />
          </div>
          <span className="tabular w-10 text-right text-xs text-signal">
            {percent(job.progress)}
          </span>
          {job.videos_total > 0 && (
            <span className="tabular text-xs text-faint">
              {job.videos_done}/{job.videos_total} videos
            </span>
          )}
        </div>
      )}

      {job.error && (
        <pre className="relative z-10 mt-2 max-h-24 overflow-auto whitespace-pre-wrap rounded-[3px] border border-reject/30 bg-reject/5 px-2 py-1.5 font-mono text-xs text-reject">
          {job.error}
        </pre>
      )}
    </div>
  );
}
