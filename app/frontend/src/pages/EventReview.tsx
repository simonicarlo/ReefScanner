import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { keys, useEvents, useSaveLabel, useSpecies } from "../lib/queries";
import type { ReefEvent, Verdict } from "../lib/types";
import { basename, duration, score, timecode } from "../lib/format";
import { BboxOverlay } from "../components/BboxOverlay";
import { Button, Empty, ErrorNote, Readout, Spinner, cx } from "../components/ui";

const VERDICT_STYLE: Record<
  Verdict,
  { key: string; label: string; classes: string }
> = {
  TP: {
    key: "T",
    label: "Confirmed",
    classes: "border-signal/60 bg-signal/15 text-signal hover:bg-signal/25",
  },
  FP: {
    key: "F",
    label: "Rejected",
    classes: "border-reject/60 bg-reject/15 text-reject hover:bg-reject/25",
  },
  unsure: {
    key: "U",
    label: "Unsure",
    classes: "border-hedge/60 bg-hedge/15 text-hedge hover:bg-hedge/25",
  },
};

export function EventReview() {
  const { jobId, eventId } = useParams();
  const jid = Number(jobId);
  const eid = Number(eventId);
  const navigate = useNavigate();

  // The whole job's events, so ← / → can move through them. One request beats
  // a round trip per keystroke when someone is holding the arrow key down.
  const { data: page } = useEvents(jid, { limit: 1000, offset: 0 });
  const { data: event, isLoading } = useQuery({
    queryKey: keys.event(eid),
    queryFn: () => api.getEvent(eid),
  });
  const { data: speciesOptions } = useSpecies(jid);
  const saveLabel = useSaveLabel(jid);
  const queryClient = useQueryClient();

  // Puts an event back in the review queue.
  const clearLabel = useMutation({
    mutationFn: () => api.deleteLabel(eid),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: keys.event(eid) });
      queryClient.invalidateQueries({ queryKey: ["events", jid] });
    },
  });

  const [species, setSpecies] = useState("");
  const [notes, setNotes] = useState("");
  const [showBox, setShowBox] = useState(true);
  const [view, setView] = useState<"clip" | "peak">("clip");

  const videoRef = useRef<HTMLVideoElement>(null);
  const speciesRef = useRef<HTMLInputElement>(null);

  const siblings = page?.items ?? [];
  const index = siblings.findIndex((e) => e.id === eid);
  const previous = index > 0 ? siblings[index - 1] : null;
  const next = index >= 0 && index < siblings.length - 1 ? siblings[index + 1] : null;

  // The next event nobody has judged yet — the natural landing spot after a
  // verdict, so a reviewer never walks back over finished work.
  const nextUnreviewed = useMemo(() => {
    if (index < 0) return null;
    return (
      siblings.slice(index + 1).find((e) => !e.label) ??
      siblings.find((e) => !e.label && e.id !== eid) ??
      null
    );
  }, [siblings, index, eid]);

  // Reset the form whenever the event changes, and prefill an existing verdict.
  useEffect(() => {
    setSpecies(event?.label?.species ?? "");
    setNotes(event?.label?.notes ?? "");
  }, [event?.id, event?.label?.species, event?.label?.notes]);

  const goTo = useCallback(
    (target: ReefEvent | null) => {
      if (target) navigate(`/jobs/${jid}/events/${target.id}`);
    },
    [navigate, jid],
  );

  const record = useCallback(
    (verdict: Verdict, advance = true) => {
      if (!event) return;
      saveLabel.mutate(
        {
          eventId: event.id,
          verdict,
          species: species.trim() || null,
          notes: notes.trim() || null,
          tight_bbox: event.label?.tight_bbox ?? null,
        },
        { onSuccess: () => advance && goTo(nextUnreviewed ?? next) },
      );
    },
    [event, species, notes, saveLabel, goTo, nextUnreviewed, next],
  );

  // Keyboard is the primary interface here: the mouse is for the odd correction,
  // not for six hundred verdicts.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      const typing =
        target.tagName === "INPUT" || target.tagName === "TEXTAREA";

      if (typing) {
        // Escape leaves a field so the shortcuts come back.
        if (e.key === "Escape") target.blur();
        // Enter in the species box means "done, save and move on".
        if (e.key === "Enter" && target.tagName === "INPUT") {
          e.preventDefault();
          target.blur();
          record("TP");
        }
        return;
      }

      switch (e.key.toLowerCase()) {
        case "t":
          e.preventDefault();
          record("TP");
          break;
        case "f":
          e.preventDefault();
          record("FP");
          break;
        case "u":
          e.preventDefault();
          record("unsure");
          break;
        case "b":
          e.preventDefault();
          setShowBox((v) => !v);
          break;
        case "s":
          e.preventDefault();
          speciesRef.current?.focus();
          break;
        case "arrowleft":
          e.preventDefault();
          goTo(previous);
          break;
        case "arrowright":
          e.preventDefault();
          goTo(next);
          break;
        case " ": {
          e.preventDefault();
          const video = videoRef.current;
          if (video) video.paused ? void video.play() : video.pause();
          break;
        }
      }
    };

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [record, goTo, previous, next]);

  if (isLoading) return <Spinner label="Loading event" />;
  if (!event) return <Empty title="Event not found" />;

  const verdict = event.label?.verdict;

  return (
    <div className="rise space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="min-w-0">
          <Link to={`/jobs/${jid}`} className="legend hover:text-signal">
            ← Run #{jid}
          </Link>
          <h1 className="tabular mt-1 truncate text-xl font-semibold">
            {event.event_id}
          </h1>
          <p className="truncate font-mono text-xs text-faint" title={event.source_video}>
            {basename(event.source_video)} @ {timecode(event.start_seconds)}
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Button size="sm" disabled={!previous} onClick={() => goTo(previous)}>
            ←
          </Button>
          <span className="tabular text-xs text-faint">
            {index >= 0 ? index + 1 : "?"} / {siblings.length}
          </span>
          <Button size="sm" disabled={!next} onClick={() => goTo(next)}>
            →
          </Button>
        </div>
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="space-y-3">
          {/* The media box is given the source video's aspect ratio, so the
              overlay's percentage coordinates land on the picture rather than
              on letterbox bars. */}
          <div
            className="panel relative mx-auto overflow-hidden bg-black"
            style={{
              aspectRatio:
                event.frame_width && event.frame_height
                  ? `${event.frame_width} / ${event.frame_height}`
                  : "16 / 9",
              // Sized from the height so a 4:3 clip can't fill the viewport and
              // push the verdict buttons below the fold. Width follows the
              // aspect ratio, and max-width keeps a very wide clip in its lane.
              height: "min(56vh, 40rem)",
              maxWidth: "100%",
            }}
          >
            {view === "clip" && event.clip_url ? (
              <video
                ref={videoRef}
                key={event.clip_url}
                src={event.clip_url}
                controls
                autoPlay
                loop
                muted
                playsInline
                className="h-full w-full"
              />
            ) : event.thumbnail_url ? (
              <img
                src={event.thumbnail_url}
                alt={`Peak frame of ${event.event_id}`}
                className="h-full w-full object-contain"
              />
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-faint">
                No media on disk for this event.
              </div>
            )}

            <BboxOverlay
              bbox={event.label?.tight_bbox ?? event.peak_bbox}
              frameWidth={event.frame_width}
              frameHeight={event.frame_height}
              visible={showBox}
              tone={event.label?.tight_bbox ? "hedge" : "signal"}
            />
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <div className="flex overflow-hidden rounded-[3px] border border-rule">
              {(["clip", "peak"] as const).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  onClick={() => setView(mode)}
                  className={cx(
                    "px-2.5 py-1 font-mono text-xs transition-colors",
                    view === mode
                      ? "bg-signal/15 text-signal"
                      : "text-faint hover:text-read",
                  )}
                >
                  {mode === "clip" ? "Clip" : "Peak frame"}
                </button>
              ))}
            </div>

            <Button
              size="sm"
              variant={showBox ? "primary" : "quiet"}
              onClick={() => setShowBox((v) => !v)}
            >
              Detection box <Kbd>B</Kbd>
            </Button>

            <span className="text-xs text-faint">
              Box marks the peak frame — on the clip it's a pointer, not a track.
            </span>
          </div>

          <div className="panel grid grid-cols-2 gap-4 p-4 sm:grid-cols-4">
            <Readout label="Start" value={timecode(event.start_seconds)} />
            <Readout label="Length" value={duration(event.duration_seconds)} />
            <Readout
              label="Confidence"
              value={score(event.ml_confidence)}
              tone={event.ml_confidence === null ? "dim" : "signal"}
            />
            <Readout label="Motion" value={score(event.motion_score, 0)} tone="dim" />
            {event.detected_class && (
              <Readout label="Class" value={event.detected_class} tone="signal" />
            )}
            {event.start_timestamp && (
              <Readout
                label="Wall clock"
                value={new Date(event.start_timestamp).toLocaleTimeString()}
                tone="dim"
              />
            )}
          </div>
        </div>

        {/* Verdict panel */}
        <aside className="space-y-4 lg:sticky lg:top-20 lg:self-start">
          <div className="panel space-y-4 p-4">
            <div>
              <div className="legend mb-2">Verdict</div>
              <div className="grid gap-1.5">
                {(Object.keys(VERDICT_STYLE) as Verdict[]).map((v) => {
                  const style = VERDICT_STYLE[v];
                  const active = verdict === v;
                  return (
                    <button
                      key={v}
                      type="button"
                      onClick={() => record(v)}
                      disabled={saveLabel.isPending}
                      className={cx(
                        "flex items-center justify-between rounded-[3px] border px-3 py-2 text-sm transition-colors",
                        active
                          ? style.classes
                          : "border-rule text-dim hover:border-rule-hi hover:text-read",
                      )}
                    >
                      <span className="flex items-center gap-2">
                        {active && <span className="h-1.5 w-1.5 rounded-full bg-current" />}
                        {style.label}
                      </span>
                      <Kbd>{style.key}</Kbd>
                    </button>
                  );
                })}
              </div>
            </div>

            <label className="block">
              <span className="legend mb-1.5 block">
                Species <Kbd>S</Kbd>
              </span>
              <input
                ref={speciesRef}
                list="species-options"
                value={species}
                onChange={(e) => setSpecies(e.target.value)}
                placeholder="e.g. grey reef shark"
                className="w-full rounded-[3px] border border-rule bg-abyss/60 px-2.5 py-1.5 text-sm text-read placeholder:text-faint focus:border-signal/60 focus:outline-none"
              />
              <datalist id="species-options">
                {speciesOptions?.map((s) => (
                  <option key={s} value={s} />
                ))}
              </datalist>
            </label>

            <label className="block">
              <span className="legend mb-1.5 block">Notes</span>
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={3}
                placeholder="Anything worth remembering about this sighting."
                className="w-full resize-y rounded-[3px] border border-rule bg-abyss/60 px-2.5 py-1.5 text-sm text-read placeholder:text-faint focus:border-signal/60 focus:outline-none"
              />
            </label>

            <ErrorNote error={saveLabel.error} />

            {event.label && (
              <button
                type="button"
                onClick={() => clearLabel.mutate()}
                disabled={clearLabel.isPending}
                className="legend hover:text-reject"
              >
                {clearLabel.isPending ? "Clearing…" : "Clear verdict"}
              </button>
            )}
          </div>

          <div className="panel p-4">
            <div className="legend mb-2">Shortcuts</div>
            <dl className="space-y-1.5 text-xs text-faint">
              {[
                ["T / F / U", "Confirm · reject · unsure"],
                ["← →", "Previous / next event"],
                ["Space", "Play / pause"],
                ["B", "Toggle detection box"],
                ["S", "Jump to species"],
                ["Enter", "Save from species field"],
              ].map(([k, description]) => (
                <div key={k} className="flex items-center justify-between gap-3">
                  <dt>
                    <Kbd>{k}</Kbd>
                  </dt>
                  <dd className="text-right">{description}</dd>
                </div>
              ))}
            </dl>
            <p className="mt-3 border-t border-rule pt-3 text-xs text-faint">
              A verdict jumps to the next unreviewed event, so you can work
              through a run without touching the mouse.
            </p>
          </div>
        </aside>
      </div>
    </div>
  );
}

function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="rounded-[3px] border border-rule-hi bg-abyss px-1.5 py-0.5 font-mono text-[10px] text-dim">
      {children}
    </kbd>
  );
}
