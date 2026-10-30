import type { ReactNode } from "react";
import styles from "./BboxOverlay.module.css";

/**
 * Draws a detection box over a video or image.
 *
 * Boxes are fractions of the frame, as Camtrap DP stores them, so they map
 * straight onto percentages of the element. That keeps the box glued to the
 * animal as the window resizes, which is the only behaviour that matters here.
 *
 * White until the event has a verdict, then the verdict's colour. Dashed when
 * a reviewer's box replaced the detector's.
 */
export function BboxOverlay({
  bbox,
  visible = true,
  color = "var(--knob)",
  corrected = false,
  label,
  compact = false,
}: {
  bbox: number[] | null;
  visible?: boolean;
  color?: string;
  corrected?: boolean;
  /** A small glass pill above the box, e.g. the class and score. */
  label?: ReactNode;
  /** Thinner lines and corners, for thumbnails. */
  compact?: boolean;
}) {
  if (!visible || !bbox || bbox.length !== 4) return null;
  const [x, y, w, h] = bbox;

  return (
    <div className={styles.layer} aria-hidden="true">
      <div
        className={[styles.box, compact && styles.compact, corrected && styles.corrected]
          .filter(Boolean)
          .join(" ")}
        style={{
          left: `${x * 100}%`,
          top: `${y * 100}%`,
          width: `${w * 100}%`,
          height: `${h * 100}%`,
          borderColor: color,
        }}
      >
        {label && (
          // Below the box when it touches the top edge, so it stays on screen.
          <span className={y < 0.08 ? `${styles.pill} ${styles.below}` : styles.pill}>{label}</span>
        )}
      </div>
    </div>
  );
}
