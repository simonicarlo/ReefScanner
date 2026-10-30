import { Link } from "react-router-dom";
import type { Job } from "../lib/types";
import { percent, shortDate } from "../lib/format";
import { Button, Tag } from "./ui";
import styles from "./JobRow.module.css";

const TONE = {
  running: "accent",
  pending: "neutral",
  done: "green",
  failed: "red",
  cancelled: "orange",
} as const;

/** One run in a project's list. The whole row opens it. */
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
    <div className={styles.row}>
      <div className={styles.line}>
        {/* Stretched link: a real anchor for keyboard and middle-click, whose
            ::after covers the row so anywhere is clickable. */}
        <Link to={`/jobs/${job.id}`} className={styles.title}>
          {job.source ? "Import" : "Run"} #{job.id}
        </Link>
        <Tag tone={TONE[job.status]}>{job.status}</Tag>
        <span className={styles.message}>{job.message}</span>
        <span className={styles.date}>{shortDate(job.started_at)}</span>
        <span className={hasEvents ? styles.count : `${styles.count} ${styles.none}`}>
          <b>{job.events_found}</b> {job.events_found === 1 ? "event" : "events"}
        </span>

        {live && onCancel ? (
          // Above the stretched link, or the row would swallow the click.
          <Button size="sm" variant="danger" className={styles.above} onClick={() => onCancel(job.id)}>
            Stop
          </Button>
        ) : resumable && onResume ? (
          <Button size="sm" className={styles.above} onClick={() => onResume(job.id)}>
            Resume
          </Button>
        ) : (
          <svg className={styles.chevron} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M6 3l5 5-5 5" />
          </svg>
        )}
      </div>

      {live && (
        <div className={styles.progress}>
          <div className={styles.track}>
            <i style={{ width: `${Math.max(2, job.progress * 100)}%` }} />
          </div>
          <span className={styles.percent}>{percent(job.progress)}</span>
          {job.videos_total > 0 && (
            <span className={styles.videos}>
              {job.videos_done} of {job.videos_total} videos
            </span>
          )}
        </div>
      )}

      {job.error && <pre className={styles.error}>{job.error}</pre>}
    </div>
  );
}
