import { useDesktopBridge, useRestartToUpdate, useStartUpdate, useUpdateStatus } from "../lib/queries";
import { Button, ErrorNote } from "./ui";
import styles from "./UpdateBanner.module.css";

/**
 * A newer ReefScanner, offered at the foot of the sidebar. Only in the
 * desktop window, and only once there is something to do: checking, being
 * up to date and being offline all show nothing. Nothing happens without a
 * click, and restarting waits for a running scan (desktop/update.py).
 */
export function UpdateBanner() {
  const bridge = useDesktopBridge();
  const status = useUpdateStatus(bridge);
  const start = useStartUpdate(bridge);
  const restart = useRestartToUpdate(bridge);

  const update = status.data;
  if (!bridge || !update) return null;
  const version = update.version ? `ReefScanner ${update.version}` : "A new version";

  let body;
  switch (update.state) {
    case "available":
      body = (
        <>
          <p>{version} is available.</p>
          <Button size="sm" variant="primary" disabled={start.isPending} onClick={() => start.mutate()}>
            Update
          </Button>
        </>
      );
      break;
    case "downloading":
      body = (
        <>
          <p>Downloading {version}…</p>
          <progress className={styles.progress} max={100} value={update.progress} />
        </>
      );
      break;
    case "verifying":
      body = <p>Checking the download…</p>;
      break;
    case "ready":
      body = (
        <>
          <p>{version} is ready.</p>
          {restart.data?.reason === "scanning" && (
            <p className={styles.hint}>Finish or stop the running scan first.</p>
          )}
          <Button size="sm" variant="primary" disabled={restart.isPending} onClick={() => restart.mutate()}>
            Restart to update
          </Button>
        </>
      );
      break;
    case "failed":
      body = (
        <>
          <p>The update didn't work. You can download it instead.</p>
          <Button size="sm" onClick={() => void bridge.open_download_page()}>
            Download
          </Button>
        </>
      );
      break;
    default:
      return null;
  }

  return (
    <section className={styles.banner} aria-live="polite">
      {body}
      {start.error && <ErrorNote error={start.error} />}
      {restart.error && <ErrorNote error={restart.error} />}
    </section>
  );
}
