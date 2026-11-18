import type { Tone } from "../components/ui";
import type { Verdict } from "./types";

/**
 * How each verdict looks and is entered, everywhere in the app. Colour always
 * comes with a symbol, so a verdict reads without colour too.
 */
export const VERDICT_INFO: Record<
  Verdict,
  {
    label: string;
    short: string;
    key: string;
    tone: Tone;
    /** On the app's own surfaces; follows light and dark. */
    color: string;
    /** Drawn on footage, which looks the same in both modes. */
    mark: string;
  }
> = {
  TP: {
    label: "Confirmed",
    short: "Confirmed",
    key: "T",
    tone: "green",
    color: "var(--green)",
    mark: "var(--mark-green)",
  },
  FP: {
    label: "Nothing there",
    short: "Nothing",
    key: "F",
    tone: "red",
    color: "var(--red)",
    mark: "var(--mark-red)",
  },
  "FP-other": {
    label: "Something else",
    short: "Other",
    key: "O",
    tone: "red",
    color: "var(--red)",
    mark: "var(--mark-red)",
  },
  unsure: {
    label: "Unsure",
    short: "Unsure",
    key: "U",
    tone: "orange",
    color: "var(--orange)",
    mark: "var(--mark-orange)",
  },
};

/** In the order they're offered. */
export const VERDICT_ORDER: Verdict[] = ["TP", "FP", "FP-other", "unsure"];
