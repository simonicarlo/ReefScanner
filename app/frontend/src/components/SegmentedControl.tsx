import { useLayoutEffect, useRef, useState, type CSSProperties } from "react";
import styles from "./SegmentedControl.module.css";

interface Option<T extends string> {
  value: T;
  label: string;
}

/**
 * A row of mutually exclusive choices with a thumb that slides to the chosen
 * one. The thumb is sized from the chosen button, since labels differ in width.
 */
export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  label,
  disabled,
}: {
  options: readonly Option<T>[];
  value: T;
  onChange: (value: T) => void;
  /** Read by screen readers; the visible label is the caller's. */
  label: string;
  disabled?: boolean;
}) {
  const buttons = useRef(new Map<T, HTMLButtonElement>());
  const [thumb, setThumb] = useState<CSSProperties>({ opacity: 0 });

  useLayoutEffect(() => {
    const place = () => {
      const on = buttons.current.get(value);
      if (!on) return;
      setThumb({ width: on.offsetWidth, transform: `translateX(${on.offsetLeft - 2}px)` });
    };
    place();
    // The system font can load after first paint and change label widths.
    void document.fonts?.ready.then(place);
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [value, options]);

  return (
    <div className={styles.seg} role="radiogroup" aria-label={label}>
      <span className={styles.thumb} style={thumb} aria-hidden="true" />
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="radio"
          aria-checked={option.value === value}
          disabled={disabled}
          className={styles.option}
          ref={(el) => {
            if (el) buttons.current.set(option.value, el);
            else buttons.current.delete(option.value);
          }}
          onClick={() => option.value !== value && onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
