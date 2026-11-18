import { createContext, useCallback, useContext } from "react";

export interface ToastMessage {
  text: string;
  /** "done" shows a green tick; "info" shows no mark. */
  kind: "done" | "info";
}

export const ToastContext = createContext<(message: ToastMessage) => void>(() => {});

/** Shows a short message at the bottom of the window, e.g. after a save. */
export function useToast(): (text: string, kind?: ToastMessage["kind"]) => void {
  const show = useContext(ToastContext);
  // Stable, so callers can list it in effect and callback dependencies.
  return useCallback((text, kind = "done") => show({ text, kind }), [show]);
}
