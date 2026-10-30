import styles from "./Switch.module.css";

/**
 * An on/off toggle. `label` names it, beside the switch or, with
 * `hideLabel`, only for screen readers (when the row already says it).
 */
export function Switch({
  checked,
  onChange,
  label,
  hideLabel,
  disabled,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  hideLabel?: boolean;
  disabled?: boolean;
}) {
  return (
    <label className={styles.row}>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={hideLabel ? label : undefined}
        disabled={disabled}
        className={styles.switch}
        onClick={() => onChange(!checked)}
      />
      {!hideLabel && <span>{label}</span>}
    </label>
  );
}
