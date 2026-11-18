import {
  useCheckForUpdates,
  useDesktopBridge,
  useHealth,
  useRestartToUpdate,
  useStartUpdate,
  useUpdateStatus,
} from "../lib/queries";
import type { UpdateStatus } from "../lib/types";
import { SettingsGroup, SettingsRow } from "./SettingsGroup";
import { Button, ErrorNote, Tag } from "./ui";

/**
 * Which ReefScanner this is, whether a newer one exists, and where its data
 * and log live. The buttons need the desktop window (its bridge); in a
 * browser tab the version and the data folder are still shown.
 */
export function AboutPanel() {
  const health = useHealth();
  const bridge = useDesktopBridge();
  const update = useUpdateStatus(bridge);
  const check = useCheckForUpdates(bridge);
  const start = useStartUpdate(bridge);
  const restart = useRestartToUpdate(bridge);

  const version = health.data?.version;
  const folder = health.data?.db.replace(/[/\\][^/\\]*$/, "");

  return (
    <SettingsGroup
      id="about-title"
      title="About ReefScanner"
      after={
        <>
          <ErrorNote error={health.error} />
          <ErrorNote error={update.error ?? check.error ?? start.error ?? restart.error} />
        </>
      }
    >
      <SettingsRow label="Version">
        <span>{version ?? "…"}</span>
        {version?.includes("-") && <Tag tone="orange">Release candidate</Tag>}
      </SettingsRow>

      {bridge && update.data && (
        <SettingsRow label="Updates" hint={updateHint(update.data, restart.data?.reason)}>
          {update.data.state === "available" && (
            <Button size="sm" variant="primary" disabled={start.isPending} onClick={() => start.mutate()}>
              Update
            </Button>
          )}
          {update.data.state === "ready" && (
            <Button size="sm" variant="primary" disabled={restart.isPending} onClick={() => restart.mutate()}>
              Restart to update
            </Button>
          )}
          {update.data.state === "failed" && (
            <Button size="sm" onClick={() => void bridge.open_download_page()}>
              Download
            </Button>
          )}
          {["none", "unreachable", "checking"].includes(update.data.state) && (
            <Button
              size="sm"
              disabled={update.data.state === "checking" || check.isPending}
              onClick={() => check.mutate()}
            >
              Check now
            </Button>
          )}
        </SettingsRow>
      )}

      <SettingsRow
        label="Data"
        hint={folder ? `Projects, reviews, and backups taken before updates: ${folder}` : "…"}
      >
        {bridge && (
          <Button size="sm" onClick={() => void bridge.show_data_folder()}>
            Show in Finder
          </Button>
        )}
      </SettingsRow>

      {bridge && (
        <SettingsRow label="Log" hint="What the app did. Send it along when something goes wrong.">
          <Button size="sm" onClick={() => void bridge.show_log()}>
            Show in Finder
          </Button>
        </SettingsRow>
      )}
    </SettingsGroup>
  );
}

function updateHint(update: UpdateStatus, refused?: string): string {
  const next = update.version ? `ReefScanner ${update.version}` : "A new version";
  const candidates = update.prereleases ? " Release candidates are included." : "";
  switch (update.state) {
    case "off":
      return "Updates are off when running from source.";
    case "checking":
      return "Checking…";
    case "none":
      return `Up to date.${candidates}`;
    case "unreachable":
      return "Couldn't reach GitHub. Are you online?";
    case "available":
      return `${next} is available.`;
    case "downloading":
      return `Downloading ${next}… ${update.progress}%`;
    case "verifying":
      return "Checking the download…";
    case "ready":
      return refused === "scanning"
        ? `${next} is ready. Finish or stop the running scan first.`
        : `${next} is ready.`;
    case "failed":
      return "The update didn't work. You can download it instead.";
  }
}
