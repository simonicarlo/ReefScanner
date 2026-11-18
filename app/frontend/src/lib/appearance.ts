import { useEffect } from "react";
import { useAppearance } from "./queries";
import type { Appearance } from "./types";

export const DEFAULT_APPEARANCE: Appearance = { mode: "system", translucency: true };

const DARK_QUERY = "(prefers-color-scheme: dark)";

/** Puts the appearance on <html>, where styles/tokens.css reads it. */
export function applyAppearance({ mode, translucency }: Appearance): void {
  const dark = mode === "dark" || (mode === "system" && matchMedia(DARK_QUERY).matches);
  const root = document.documentElement;
  root.dataset.mode = dark ? "dark" : "light";
  root.dataset.glass = translucency ? "on" : "off";
}

/** Keeps <html> in step with the saved appearance and, on "system", with macOS. */
export function useApplyAppearance(): void {
  const appearance = useAppearance().data ?? DEFAULT_APPEARANCE;

  useEffect(() => {
    applyAppearance(appearance);
    if (appearance.mode !== "system") return;
    const media = matchMedia(DARK_QUERY);
    const follow = () => applyAppearance(appearance);
    media.addEventListener("change", follow);
    return () => media.removeEventListener("change", follow);
  }, [appearance]);
}
