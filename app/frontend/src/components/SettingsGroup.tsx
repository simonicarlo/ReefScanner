import type { ReactNode } from "react";
import styles from "./SettingsGroup.module.css";

/**
 * A titled group of rows, as in macOS Settings: a label (and hint) on the
 * left, its control or value on the right. Appearance and About use it.
 */
export function SettingsGroup({
  id,
  title,
  after,
  children,
}: {
  id: string;
  title: string;
  /** Below the rows, outside the group: an error, say. */
  after?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className={styles.panel} aria-labelledby={id}>
      <h2 id={id} className={styles.title}>
        {title}
      </h2>
      <div className={styles.group}>{children}</div>
      {after}
    </section>
  );
}

export function SettingsRow({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className={styles.row}>
      <div className={styles.text}>
        <span>{label}</span>
        {hint && <span className={styles.hint}>{hint}</span>}
      </div>
      {children && <div className={styles.control}>{children}</div>}
    </div>
  );
}
