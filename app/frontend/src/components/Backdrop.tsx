import { useEffect, useRef, useState } from "react";
import styles from "./Backdrop.module.css";

interface Layer {
  id: number;
  url: string | null;
}

/** How long the old frame stays while the new one fades in; matches the CSS. */
const CROSSFADE_MS = 600;

/** A CSS url() for a path that may hold spaces, quotes or brackets (event ids
 * come from file names). Quoted, with the string's own escapes. */
function cssUrl(url: string): string {
  return `url("${url.replace(/[\\"\n\r]/g, (c) => `\\${c.charCodeAt(0).toString(16)} `)}")`;
}

/**
 * The current frame, blurred and enlarged behind the whole window, so the
 * glass panes take their colour from the dive. A still image, never the
 * playing video. Changing frames crossfades.
 */
export function Backdrop({ url }: { url: string | null }) {
  const nextId = useRef(0);
  const [layers, setLayers] = useState<Layer[]>([]);

  useEffect(() => {
    const id = ++nextId.current;
    // Keep only the frame being replaced, so it can fade out under the new one.
    setLayers((prev) => [...prev.slice(-1), { id, url }]);
    const timer = setTimeout(
      () => setLayers((prev) => prev.filter((layer) => layer.id === id)),
      CROSSFADE_MS,
    );
    return () => clearTimeout(timer);
  }, [url]);

  return (
    <div className={styles.backdrop} aria-hidden="true">
      {layers.map((layer, i) => (
        <div
          key={layer.id}
          className={i === layers.length - 1 ? styles.entering : styles.leaving}
        >
          {layer.url && (
            <div
              className={styles.image}
              style={{ backgroundImage: cssUrl(layer.url) }}
            />
          )}
        </div>
      ))}
    </div>
  );
}
