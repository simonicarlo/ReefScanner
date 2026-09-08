/** Seconds -> m:ss (or h:mm:ss past an hour). Used for every timecode. */
export function timecode(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const total = Math.floor(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const mm = h > 0 ? String(m).padStart(2, "0") : String(m);
  return `${h > 0 ? `${h}:` : ""}${mm}:${String(s).padStart(2, "0")}`;
}

/** Duration in the compact form used on event cards. */
export function duration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  return timecode(seconds);
}

/** Just the filename — full paths are long and the folder is the same. */
export function basename(path: string): string {
  return path.split(/[\\/]/).pop() || path;
}

/**
 * The identifying tail of a path: ".../footage/ningaloo".
 *
 * A bare basename is useless for folders — half of them are called "in" or
 * "out" — and the full path is too long for a card. The last couple of
 * segments are what someone actually recognises.
 */
export function tailPath(path: string, segments = 2): string {
  const parts = path.split(/[\\/]/).filter(Boolean);
  if (parts.length <= segments) return path;
  return `…/${parts.slice(-segments).join("/")}`;
}

export function percent(fraction: number): string {
  return `${Math.round(fraction * 100)}%`;
}

/** A confidence or motion score, or an em dash when the mode didn't produce one. */
export function score(value: number | null | undefined, digits = 2): string {
  return value === null || value === undefined ? "—" : value.toFixed(digits);
}

export function shortDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
