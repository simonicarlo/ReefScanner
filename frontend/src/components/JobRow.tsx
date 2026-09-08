import { Link } from "react-router-dom";
import type { Job } from "../lib/types";
import { percent, shortDate } from "../lib/format";
import { Button, Tag, cx } from "./ui";

const TONE = {
  running: "signal",
  pending: "neutral",
  done: "signal",
  failed: "reject",
  cancelled: "hedge",
} as const;

export function JobRow({
  job,
  onCancel,
}: {
  job: Job;
  onCancel?: (id: number) => void;
}) {
  const live = job.status === "running" || job.status === "pending";

  return (
    <div className="panel px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Link
          to={`/jobs/${job.id}`}
          className="tabular text-sm text-read hover:text-signal"
        >
          Run #{job.id}
        </Link>

        <Tag tone={TONE[job.status]}>
          {live && <span className="pulse-dot h-1 w-1 rounded-full bg-current" />}
          {job.status}
        </Tag>

        <span className="min-w-0 flex-1 truncate text-sm text-faint">
          {job.message || "—"}
        </span>

        <span className="tabular text-xs text-dim">
          {job.events_found} event{job.events_found === 1 ? "" : "s"}
        </span>
        <span className="tabular text-xs text-faint">
          {shortDate(job.started_at)}
        </span>

        {live && onCancel && (
          <Button size="sm" variant="danger" onClick={() => onCancel(job.id)}>
            Stop
          </Button>
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
            <div className={cx("absolute inset-0 overflow-hidden", "sweeping")} />
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
        <pre className="mt-2 max-h-24 overflow-auto whitespace-pre-wrap rounded-[3px] border border-reject/30 bg-reject/5 px-2 py-1.5 font-mono text-xs text-reject">
          {job.error}
        </pre>
      )}
    </div>
  );
}
