import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { ToastContext, type ToastMessage } from "../lib/toast";
import styles from "./Toast.module.css";

/** How long a message stays before it slides away. */
const VISIBLE_MS = 2600;

/**
 * One message at a time, at the bottom of the window. A new message replaces
 * the one showing, so a quick run of saves never stacks up.
 */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<(ToastMessage & { id: number }) | null>(null);
  const nextId = useRef(0);

  const show = useCallback((message: ToastMessage) => {
    setToast({ ...message, id: ++nextId.current });
  }, []);

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), VISIBLE_MS);
    return () => clearTimeout(timer);
  }, [toast]);

  return (
    <ToastContext value={show}>
      {children}
      <div className={styles.region} role="status" aria-live="polite">
        {toast && (
          <div key={toast.id} className={styles.toast}>
            {toast.kind === "done" && (
              <span className={styles.tick} aria-hidden="true">
                <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M3 8.5l3.2 3L13 4.5" />
                </svg>
              </span>
            )}
            {toast.text}
          </div>
        )}
      </div>
    </ToastContext>
  );
}
