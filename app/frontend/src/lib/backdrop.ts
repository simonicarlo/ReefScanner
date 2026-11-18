import { createContext, useContext, useEffect } from "react";

/** Sets the frame blurred behind the window; null for none. */
export const BackdropContext = createContext<(url: string | null) => void>(() => {});

/**
 * Shows `url` blurred behind the window while the calling page is mounted.
 * Pages pass the frame they're about: the event under review, or a project's
 * cover. Leaving the page clears it.
 */
export function useBackdrop(url: string | null | undefined): void {
  const setBackdrop = useContext(BackdropContext);
  useEffect(() => {
    setBackdrop(url ?? null);
    return () => setBackdrop(null);
  }, [url, setBackdrop]);
}
