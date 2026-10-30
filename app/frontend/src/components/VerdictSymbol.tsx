import type { Verdict } from "../lib/types";

/** The verdict's symbol: ✓ confirmed, ✕ nothing there, − something else, ? unsure. */
export function VerdictSymbol({ verdict }: { verdict: Verdict }) {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {verdict === "TP" && <path d="M3 8.5l3.2 3L13 4.5" strokeWidth="2.4" />}
      {verdict === "FP" && <path d="M4 4l8 8M12 4l-8 8" strokeWidth="2.4" />}
      {verdict === "FP-other" && <path d="M4 8h8" strokeWidth="2.4" />}
      {verdict === "unsure" && (
        <>
          <path d="M6 6a2 2 0 1 1 2.6 1.9c-.4.2-.6.5-.6 1V9.5" strokeWidth="2.2" />
          <path d="M8 12h.01" strokeWidth="2.4" />
        </>
      )}
    </svg>
  );
}
