import type { ReactNode, ButtonHTMLAttributes, InputHTMLAttributes } from "react";
import { ApiError } from "../lib/api";
import styles from "./ui.module.css";

/** Tiny classname joiner. A dependency for this would be silly. */
export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  /** primary: the one main action. quiet: everything else. ghost: no chrome
   * until hovered. danger: deletes or stops something. */
  variant?: "primary" | "ghost" | "danger" | "quiet";
  size?: "sm" | "md";
};

export function Button({ variant = "quiet", size = "md", className, ...props }: ButtonProps) {
  return (
    <button
      {...props}
      className={cx(styles.button, styles[variant], size === "sm" && styles.small, className)}
    />
  );
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <label className={styles.field}>
      <span className={styles.fieldLabel}>{label}</span>
      {children}
      {hint && <span className={styles.hint}>{hint}</span>}
    </label>
  );
}

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cx(styles.input, className)} />;
}

export type Tone = "neutral" | "accent" | "green" | "red" | "orange";

/** A status: a coloured dot and a word. The colour is never the only signal. */
export function Tag({
  tone = "neutral",
  children,
  className,
}: {
  tone?: Tone;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span className={cx(styles.tag, styles[`tone-${tone}`], className)}>
      <span className={styles.dot} aria-hidden="true" />
      {children}
    </span>
  );
}

/** A labelled value. Numbers line up, so they use tabular figures. */
export function Readout({
  label,
  value,
  tone,
}: {
  label: string;
  value: ReactNode;
  tone?: "dim";
}) {
  return (
    <div className={styles.readout}>
      <div className={styles.readoutLabel}>{label}</div>
      <div className={cx(styles.readoutValue, tone === "dim" && styles.dim)}>{value}</div>
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className={styles.empty}>
      <div className={styles.emptyTitle}>{title}</div>
      {children && <div className={styles.emptyText}>{children}</div>}
    </div>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : String(error);
  const problems = error instanceof ApiError ? error.problems : [];
  return (
    <div className={styles.error} role="alert">
      <svg className={styles.errorIcon} viewBox="0 0 16 16" aria-hidden="true">
        <circle cx="8" cy="8" r="7" fill="currentColor" />
        <path d="M8 4.5v4.2M8 11.2h.01" stroke="var(--on-accent)" strokeWidth="1.8" strokeLinecap="round" />
      </svg>
      <div className={styles.errorBody}>
        {message}
        {problems.length > 0 && (
          <ul className={styles.problems}>
            {problems.map((p, i) => (
              <li key={i}>{p}</li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

/** Loading. Shows only after a moment, so quick local reads don't flash it,
 * and stays still: nothing in the app animates on its own. */
export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div className={styles.loading} role="status">
      {label}…
    </div>
  );
}
