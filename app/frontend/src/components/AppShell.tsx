import { useState, type ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { BackdropContext } from "../lib/backdrop";
import { Backdrop } from "./Backdrop";
import { ToastProvider } from "./Toast";
import styles from "./AppShell.module.css";

const NAV = [
  {
    to: "/",
    label: "Projects",
    icon: (
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
        <rect x="2" y="3" width="12" height="10" rx="2" />
        <path d="M2 6h12" />
      </svg>
    ),
  },
  {
    to: "/settings",
    label: "Settings",
    icon: (
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
        <circle cx="8" cy="8" r="2.2" />
        <path d="M8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.4 3.4l1.4 1.4M11.2 11.2l1.4 1.4M3.4 12.6l1.4-1.4M11.2 4.8l1.4-1.4" />
      </svg>
    ),
  },
];

/**
 * The window: a glass sidebar for places, the page beside it, and the frame
 * the page is about blurred behind both (see lib/backdrop.ts).
 */
export function AppShell({ children }: { children: ReactNode }) {
  const [backdrop, setBackdrop] = useState<string | null>(null);
  // "/" matches every page, so Projects stays lit through a project's runs
  // and reviews, but not on Settings.
  const onSettings = useLocation().pathname.startsWith("/settings");

  return (
    <BackdropContext value={setBackdrop}>
      <ToastProvider>
        <div className={styles.shell}>
          <Backdrop url={backdrop} />

          <aside className={styles.sidebar}>
            <NavLink to="/" className={styles.brand}>
              <span className={styles.mark} aria-hidden="true">
                <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
                  <path d="M2 9.5c1.5-1.6 3-1.6 4.5 0s3 1.6 4.5 0 2.2-1.4 3-.8" />
                  <path d="M2 6c1.5-1.6 3-1.6 4.5 0s3 1.6 4.5 0 2.2-1.4 3-.8" opacity="0.55" />
                </svg>
              </span>
              ReefScanner
            </NavLink>

            <nav className={styles.nav} aria-label="App">
              {NAV.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) =>
                    isActive && !(item.to === "/" && onSettings)
                      ? `${styles.navItem} ${styles.active}`
                      : styles.navItem
                  }
                >
                  {item.icon}
                  {item.label}
                </NavLink>
              ))}
            </nav>

            <p className={styles.status}>Local · works offline</p>
          </aside>

          <main className={styles.main}>{children}</main>
        </div>
      </ToastProvider>
    </BackdropContext>
  );
}
