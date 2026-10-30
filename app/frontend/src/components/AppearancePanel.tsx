import { DEFAULT_APPEARANCE } from "../lib/appearance";
import { useAppearance, useSaveAppearance } from "../lib/queries";
import type { AppearanceMode } from "../lib/types";
import { SegmentedControl } from "./SegmentedControl";
import { Switch } from "./Switch";
import { ErrorNote } from "./ui";
import styles from "./AppearancePanel.module.css";

const MODES: { value: AppearanceMode; label: string }[] = [
  { value: "system", label: "System" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

/** Light or dark, and translucency. Changes apply as soon as they're picked. */
export function AppearancePanel() {
  const { data, error } = useAppearance();
  const save = useSaveAppearance();
  const appearance = data ?? DEFAULT_APPEARANCE;

  return (
    <section className={styles.panel} aria-labelledby="appearance-title">
      <h2 id="appearance-title" className={styles.title}>
        Appearance
      </h2>
      <div className={styles.group}>
        <div className={styles.row}>
          <span>Mode</span>
          <SegmentedControl
            label="Mode"
            options={MODES}
            value={appearance.mode}
            disabled={!data}
            onChange={(mode) => save.mutate({ ...appearance, mode })}
          />
        </div>
        <div className={styles.row}>
          <div className={styles.text}>
            <span>Translucency</span>
            <span className={styles.hint}>
              Panes take a faint tint from the footage. Turn it off when judging
              colour matters.
            </span>
          </div>
          <Switch
            label="Translucency"
            hideLabel
            checked={appearance.translucency}
            disabled={!data}
            onChange={(translucency) => save.mutate({ ...appearance, translucency })}
          />
        </div>
      </div>
      <ErrorNote error={error ?? save.error} />
    </section>
  );
}
