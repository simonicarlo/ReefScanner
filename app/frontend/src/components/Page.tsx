import type { ReactNode } from "react";
import styles from "./Page.module.css";

/** A padded, centred page. The review screen goes edge to edge instead. */
export function Page({ children }: { children: ReactNode }) {
  return <div className={styles.page}>{children}</div>;
}
