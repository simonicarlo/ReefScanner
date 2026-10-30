import { useRef, type KeyboardEvent, type PointerEvent } from "react";
import { preciseTimecode } from "../lib/format";
import styles from "./Timeline.module.css";

/**
 * The clip's timeline, under the footage: the event's window, its peak, and
 * the playhead. Click or drag to seek; arrow keys step a second when focused.
 *
 * Positions come from where the clip starts in the source video
 * (`clipStart`). Without it the event can't be placed on the clip, so only
 * the playhead shows. The labels are source-video times, which are exact
 * either way.
 */
export function Timeline({
  clipStart,
  duration,
  current,
  start,
  end,
  peak,
  onSeek,
}: {
  clipStart: number | null;
  /** Clip length in seconds; null until known. */
  duration: number | null;
  /** Playhead in clip seconds; null to hide it. */
  current: number | null;
  start: number;
  end: number;
  peak: number;
  onSeek: (clipSeconds: number) => void;
}) {
  const track = useRef<HTMLDivElement>(null);
  const known = duration !== null && duration > 0;
  const at = (clipSeconds: number) =>
    known ? `${Math.min(100, Math.max(0, (clipSeconds / duration) * 100))}%` : "0%";
  const placed = known && clipStart !== null;

  const seekFrom = (e: PointerEvent<HTMLDivElement>) => {
    const box = track.current?.getBoundingClientRect();
    if (!box || !known) return;
    const fraction = Math.min(1, Math.max(0, (e.clientX - box.left) / box.width));
    onSeek(fraction * duration);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!known || (e.key !== "ArrowLeft" && e.key !== "ArrowRight")) return;
    // The page uses ← → for the previous and next event; here they seek.
    e.preventDefault();
    e.stopPropagation();
    const step = e.key === "ArrowLeft" ? -1 : 1;
    onSeek(Math.min(duration, Math.max(0, (current ?? 0) + step)));
  };

  return (
    <div className={styles.timeline}>
      <div
        ref={track}
        className={styles.track}
        role="slider"
        tabIndex={0}
        aria-label="Position in the clip"
        aria-valuemin={0}
        aria-valuemax={known ? duration : 0}
        aria-valuenow={current ?? 0}
        aria-valuetext={
          current !== null && clipStart !== null ? preciseTimecode(clipStart + current) : undefined
        }
        onPointerDown={(e) => {
          e.currentTarget.setPointerCapture(e.pointerId);
          seekFrom(e);
        }}
        onPointerMove={(e) => {
          if (e.currentTarget.hasPointerCapture(e.pointerId)) seekFrom(e);
        }}
        onKeyDown={onKeyDown}
      >
        <div className={styles.rail} />
        {placed && (
          <>
            <div
              className={styles.window}
              style={{ left: at(start - clipStart), right: `calc(100% - ${at(end - clipStart)})` }}
            />
            <div className={styles.peak} style={{ left: at(peak - clipStart) }} />
          </>
        )}
        {current !== null && known && (
          <>
            <div className={styles.played} style={{ width: at(current) }} />
            <div className={styles.head} style={{ left: at(current) }} />
          </>
        )}
      </div>
      <div className={styles.labels}>
        <span>
          Start <b>{preciseTimecode(start)}</b>
        </span>
        <span>
          Peak <b>{preciseTimecode(peak)}</b>
        </span>
        <span>
          End <b>{preciseTimecode(end)}</b>
        </span>
      </div>
    </div>
  );
}
