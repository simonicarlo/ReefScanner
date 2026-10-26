import { useEffect, useRef, useState } from "react";

/**
 * Draws the engine's detection box over a video or image.
 *
 * The box is in *source video* pixel coordinates while the element is laid out
 * at whatever size the panel gives it, so everything is converted to
 * percentages against the source resolution. That keeps the box glued to the
 * animal as the window resizes, which is the only behaviour that matters here.
 */
export function BboxOverlay({
  bbox,
  frameWidth,
  frameHeight,
  visible = true,
  tone = "signal",
}: {
  bbox: number[] | null;
  frameWidth: number | null;
  frameHeight: number | null;
  visible?: boolean;
  tone?: "signal" | "hedge";
}) {
  if (!visible || !bbox || bbox.length !== 4) return null;
  if (!frameWidth || !frameHeight) return null;

  const [x, y, w, h] = bbox;
  const color = tone === "signal" ? "var(--color-signal)" : "var(--color-hedge)";

  return (
    <div className="pointer-events-none absolute inset-0">
      <div
        className="absolute border-2"
        style={{
          left: `${(x / frameWidth) * 100}%`,
          top: `${(y / frameHeight) * 100}%`,
          width: `${(w / frameWidth) * 100}%`,
          height: `${(h / frameHeight) * 100}%`,
          borderColor: color,
          boxShadow: `0 0 0 1px #0008, 0 0 18px -2px ${color}`,
        }}
      >
        {/* Corner ticks: reads as an instrument reticle rather than a
            screenshot annotation, and stays visible on busy footage. */}
        {[
          "left-0 top-0 border-l-2 border-t-2",
          "right-0 top-0 border-r-2 border-t-2",
          "left-0 bottom-0 border-b-2 border-l-2",
          "right-0 bottom-0 border-b-2 border-r-2",
        ].map((pos) => (
          <span
            key={pos}
            className={`absolute h-2.5 w-2.5 ${pos}`}
            style={{ borderColor: color }}
          />
        ))}
      </div>
    </div>
  );
}

/** Tracks an element's rendered size — used to letterbox the overlay correctly. */
export function useElementSize<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setSize({ width, height });
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return [ref, size] as const;
}
