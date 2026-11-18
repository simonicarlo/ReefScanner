import { DEFAULT_APPEARANCE } from "../lib/appearance";
import { useAppearance, useSaveAppearance } from "../lib/queries";
import type { AppearanceMode } from "../lib/types";
import { SegmentedControl } from "./SegmentedControl";
import { Switch } from "./Switch";
import { SettingsGroup, SettingsRow } from "./SettingsGroup";
import { ErrorNote } from "./ui";

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
    <SettingsGroup
      id="appearance-title"
      title="Appearance"
      after={<ErrorNote error={error ?? save.error} />}
    >
      <SettingsRow label="Mode">
        <SegmentedControl
          label="Mode"
          options={MODES}
          value={appearance.mode}
          disabled={!data}
          onChange={(mode) => save.mutate({ ...appearance, mode })}
        />
      </SettingsRow>
      <SettingsRow
        label="Translucency"
        hint="Panes take a faint tint from the footage. Turn it off when judging colour matters."
      >
        <Switch
          label="Translucency"
          hideLabel
          checked={appearance.translucency}
          disabled={!data}
          onChange={(translucency) => save.mutate({ ...appearance, translucency })}
        />
      </SettingsRow>
    </SettingsGroup>
  );
}
