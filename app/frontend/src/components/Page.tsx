import type { ReactNode } from "react";
import styles from "./Page.module.css";

/**
 * A padded, centred page on the content surface. The review screen goes edge
 * to edge instead, so its panes are glass straight over the backdrop, like
 * the sidebar: chrome is one tint, content the other.
 */
export function Page({ children }: { children: ReactNode }) {
  return (
    <div className={styles.surface}>
      <div className={styles.page}>{children}</div>
    </div>
  );
}
