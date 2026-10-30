import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { keys, useEvents, useJob, useProject, useSaveReview, useSpecies } from "../lib/queries";
import type { ReefEvent, Verdict } from "../lib/types";
import { basename, clockTime, duration, eventLabel, localDate, score, timecode, timeOfDay } from "../lib/format";
import { useBackdrop } from "../lib/backdrop";
import { useToast } from "../lib/toast";
import { VERDICT_INFO, VERDICT_ORDER } from "../lib/verdicts";
import { BboxOverlay } from "../components/BboxOverlay";
import { SegmentedControl } from "../components/SegmentedControl";
import { VerdictSymbol } from "../components/VerdictSymbol";
import { Button, Empty, ErrorNote, Kbd, Spinner, cx } from "../components/ui";
import styles from "./EventReview.module.css";

const VIEWS = [
  { value: "clip", label: "Clip" },
  { value: "peak", label: "Peak frame" },
] as const;

const SHORTCUTS = [
  ["T", "Confirmed"],
  ["F", "Nothing there"],
  ["O", "Something else"],
  ["U", "Unsure"],
  ["← →", "Previous or next event"],
  ["Space", "Play or pause"],
  ["B", "Show or hide the box"],
  ["S", "Go to species"],
  ["Enter", "Save from the species field"],
  ["Esc", "Leave a field"],
];

export function EventReview() {
  const { jobId, eventId } = useParams();
  const jid = Number(jobId);
  // React Router hands the param back decoded; event ids contain ":".
  const eid = eventId ?? "";
  const navigate = useNavigate();

  // The whole job's events, so ← / → can move through them. One request beats
  // a round trip per keystroke when someone is holding the arrow key down.
  const { data: page } = useEvents(jid, { limit: 1000, offset: 0 });
  const { data: event, isLoading } = useQuery({
    queryKey: keys.event(eid),
    queryFn: () => api.getEvent(eid),
  });
  const { data: speciesOptions } = useSpecies(jid);
  const { data: job } = useJob(jid);
  const { data: project } = useProject(job?.project_id ?? 0);
  const toast = useToast();
  // The frame under review, blurred behind the window.
  useBackdrop(event?.frame_url);
  const saveReview = useSaveReview(jid);
  const queryClient = useQueryClient();

  // Puts an event back in the review queue.
  const clearReview = useMutation({
    mutationFn: () => api.deleteReview(eid),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: keys.event(eid) });
      queryClient.invalidateQueries({ queryKey: ["events", jid] });
    },
  });

  const [species, setSpecies] = useState("");
  const [notes, setNotes] = useState("");
  const [showBox, setShowBox] = useState(true);
  const [view, setView] = useState<"clip" | "peak">("clip");
  // The media's own shape (width / height), learned when it loads, so the
  // overlay's percentages land on the picture rather than on letterbox bars.
  const [aspect, setAspect] = useState(16 / 9);

  const videoRef = useRef<HTMLVideoElement>(null);
  const speciesRef = useRef<HTMLInputElement>(null);
  const currentRowRef = useRef<HTMLAnchorElement>(null);

  const siblings = useMemo(() => page?.items ?? [], [page]);
  const index = siblings.findIndex((e) => e.id === eid);
  const previous = index > 0 ? siblings[index - 1] : null;
  const next = index >= 0 && index < siblings.length - 1 ? siblings[index + 1] : null;

  // The next event nobody has judged yet — the natural landing spot after a
  // verdict, so a reviewer never walks back over finished work.
  const nextUnreviewed = useMemo(() => {
    if (index < 0) return null;
    return (
      siblings.slice(index + 1).find((e) => !e.review) ??
      siblings.find((e) => !e.review && e.id !== eid) ??
      null
    );
  }, [siblings, index, eid]);

  // Reset the form whenever the event changes, and prefill an existing verdict.
  useEffect(() => {
    setSpecies(event?.review?.scientific_name ?? "");
    setNotes(event?.review?.notes ?? "");
  }, [event?.id, event?.review?.scientific_name, event?.review?.notes]);

  const goTo = useCallback(
    (target: ReefEvent | null) => {
      if (target) navigate(`/jobs/${jid}/events/${encodeURIComponent(target.id)}`);
    },
    [navigate, jid],
  );

  const record = useCallback(
    (verdict: Verdict, advance = true) => {
      if (!event) return;
      saveReview.mutate(
        {
          eventId: event.id,
          verdict,
          scientific_name: species.trim() || null,
          notes: notes.trim() || null,
          // Keep a box a reviewer already settled; otherwise the server uses
          // the detector's.
          bbox: event.review?.bbox ?? null,
        },
        {
          onSuccess: () => {
            const left = siblings.filter((e) => !e.review && e.id !== event.id).length;
            toast(
              `${VERDICT_INFO[verdict].label}. ${
                left ? `${left} left to review.` : "Every event in this run is reviewed."
              }`,
            );
            if (advance) goTo(nextUnreviewed ?? next);
          },
        },
      );
    },
    [event, species, notes, saveReview, goTo, nextUnreviewed, next, siblings, toast],
  );

  // Keep the current event in view in the list as the reviewer moves along.
  useEffect(() => {
    currentRowRef.current?.scrollIntoView({ block: "nearest" });
  }, [eid, siblings.length]);

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
        // Enter in the species box means "done, save and move on": a TP,
        // unless the name is what an FP-other turned out to be.
        if (e.key === "Enter" && target.tagName === "INPUT") {
          e.preventDefault();
          target.blur();
          record(event?.review?.verdict === "FP-other" ? "FP-other" : "TP");
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
        case "o":
          e.preventDefault();
          record("FP-other");
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
  }, [record, goTo, previous, next, event?.review?.verdict]);

  if (isLoading) return <Spinner label="Loading event" />;
  if (!event) return <Empty title="Event not found" />;

  const verdict = event.review?.verdict;
  const reviewedBox = event.review?.bbox ?? null;
  // Dashed when the reviewer's box differs from the detector's.
  const corrected =
    reviewedBox !== null && JSON.stringify(reviewedBox) !== JSON.stringify(event.bbox);
  const reviewedCount = siblings.filter((e) => e.review).length;

  return (
    <div className={styles.review}>
      <header className={styles.toolbar}>
        <Link to={`/jobs/${jid}`} className={styles.iconButton} aria-label={`Back to run ${jid}`}>
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <path d="M10 3 5 8l5 5" />
          </svg>
        </Link>
        <div className={styles.heading}>
          <h1 title={event.id}>
            {index >= 0 ? `Event ${index + 1} of ${siblings.length}` : eventLabel(event.id)}
          </h1>
          <span>
            {project ? `${project.name} · ` : ""}Run #{jid}
          </span>
        </div>

        <div className={styles.tools}>
          <SegmentedControl label="Show" options={VIEWS} value={view} onChange={setView} />
          <button
            type="button"
            className={styles.toggle}
            aria-pressed={showBox}
            onClick={() => setShowBox((v) => !v)}
          >
            Box <Kbd>B</Kbd>
          </button>
          <div className={styles.stepper}>
            <button
              type="button"
              className={styles.iconButton}
              disabled={!previous}
              onClick={() => goTo(previous)}
              aria-label="Previous event"
            >
              <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M10 3 5 8l5 5" />
              </svg>
            </button>
            <button
              type="button"
              className={styles.iconButton}
              disabled={!next}
              onClick={() => goTo(next)}
              aria-label="Next event"
            >
              <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M6 3l5 5-5 5" />
              </svg>
            </button>
          </div>
        </div>
      </header>

      <div className={styles.body}>
        <nav className={styles.list} aria-label="Events in this run">
          <div className={styles.listHead}>
            {siblings.length} events · {reviewedCount} reviewed
          </div>
          {siblings.map((e) => {
            const current = e.id === eid;
            const v = e.review?.verdict;
            return (
              <Link
                key={e.id}
                ref={current ? currentRowRef : undefined}
                to={`/jobs/${jid}/events/${encodeURIComponent(e.id)}`}
                className={styles.row}
                aria-current={current ? "page" : undefined}
              >
                <span
                  className={cx(styles.dot, v && styles.judged)}
                  style={v ? { background: VERDICT_INFO[v].color } : undefined}
                  title={v ? VERDICT_INFO[v].label : "Not reviewed"}
                />
                <span className={styles.rowText}>
                  <span className={styles.rowTime}>{timeOfDay(e.start_time)}</span>
                  <span className={styles.rowSub}>{basename(e.source_video)}</span>
                </span>
                <span className={styles.rowScore}>{score(e.confidence)}</span>
              </Link>
            );
          })}
        </nav>

        <section className={styles.stage} aria-label="Footage">
          <div className={styles.fit}>
            <div
              className={styles.media}
              style={{ aspectRatio: aspect, width: `min(100cqw, ${aspect} * 100cqh)` }}
            >
              {view === "clip" ? (
                <video
                  ref={videoRef}
                  key={event.clip_url}
                  src={event.clip_url}
                  onLoadedMetadata={(e) => {
                    const v = e.currentTarget;
                    if (v.videoWidth && v.videoHeight) setAspect(v.videoWidth / v.videoHeight);
                  }}
                  controls
                  autoPlay
                  loop
                  muted
                  playsInline
                />
              ) : (
                <img
                  src={event.frame_url}
                  alt={`Peak frame of ${eventLabel(event.id)}`}
                  onLoad={(e) => {
                    const img = e.currentTarget;
                    if (img.naturalWidth) setAspect(img.naturalWidth / img.naturalHeight);
                  }}
                />
              )}
              <BboxOverlay
                bbox={reviewedBox ?? event.bbox}
                visible={showBox}
                color={verdict ? VERDICT_INFO[verdict].mark : undefined}
                corrected={corrected}
                label={
                  <>
                    {event.detected_class ?? "Detection"}
                    {event.confidence !== null && (
                      <span className={styles.pillScore}>{score(event.confidence)}</span>
                    )}
                  </>
                }
              />
            </div>
          </div>
          {view === "clip" && showBox && (
            <p className={styles.caption}>
              The box marks the peak frame. On the clip it shows where to look, not
              where the animal goes.
            </p>
          )}
        </section>

        <aside className={styles.inspector} aria-label="Verdict">
          <div className={styles.when}>
            {/* In the camera's timezone, never the viewer's. */}
            <p className={styles.time} title={clockTime(event.start_time)}>
              {timeOfDay(event.start_time)}
            </p>
            <p className={styles.sub}>
              {localDate(event.start_time)} · {duration(event.duration_seconds)}
            </p>
            <p className={styles.file} title={event.source_video}>
              {basename(event.source_video)} at {timecode(event.start_seconds)}
            </p>
          </div>

          <dl className={styles.facts}>
            <div>
              <dt>Score</dt>
              <dd className={styles.num}>{score(event.confidence, 3)}</dd>
            </div>
            <div>
              <dt>Peak</dt>
              <dd className={styles.num}>{timecode(event.peak_seconds)}</dd>
            </div>
            {event.detected_class && (
              <div>
                <dt>Class</dt>
                <dd>{event.detected_class}</dd>
              </div>
            )}
            <div>
              <dt>Time zone</dt>
              <dd className={styles.num}>{clockTime(event.start_time).split(" ")[1]}</dd>
            </div>
          </dl>

          <div className={styles.verdicts} role="group" aria-label="Verdict">
            {VERDICT_ORDER.map((v) => {
              const info = VERDICT_INFO[v];
              return (
                <button
                  key={v}
                  type="button"
                  className={styles.verdict}
                  style={{ "--v": info.color } as React.CSSProperties}
                  aria-pressed={verdict === v}
                  disabled={saveReview.isPending}
                  onClick={() => record(v)}
                >
                  <span className={styles.verdictTop}>
                    <span className={styles.symbol}>
                      <VerdictSymbol verdict={v} />
                    </span>
                    <kbd className={styles.verdictKey}>{info.key}</kbd>
                  </span>
                  {info.label}
                </button>
              );
            })}
          </div>

          <div className={styles.fields}>
            <label className={styles.field}>
              <span className={styles.fieldLabel}>
                {verdict === "FP-other" ? "What it was" : "Species"} <Kbd>S</Kbd>
              </span>
              <input
                ref={speciesRef}
                list="species-options"
                value={species}
                onChange={(e) => setSpecies(e.target.value)}
                placeholder="Scientific name, e.g. Triaenodon obesus"
                className={styles.input}
              />
              <datalist id="species-options">
                {speciesOptions?.map((s) => (
                  <option key={s} value={s} />
                ))}
              </datalist>
            </label>

            <label className={styles.field}>
              <span className={styles.fieldLabel}>Notes</span>
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={3}
                placeholder="Anything worth remembering about this sighting"
                className={styles.input}
              />
            </label>
          </div>

          <ErrorNote error={saveReview.error} />
          <ErrorNote error={clearReview.error} />

          <p className={styles.hint}>
            A verdict saves and moves to the next event that isn't reviewed yet.
          </p>

          {event.review && (
            <Button
              size="sm"
              variant="danger"
              className={styles.clear}
              onClick={() => clearReview.mutate()}
              disabled={clearReview.isPending}
            >
              {clearReview.isPending ? "Clearing…" : "Clear verdict"}
            </Button>
          )}

          <details className={styles.shortcuts}>
            <summary>Keyboard shortcuts</summary>
            <dl>
              {SHORTCUTS.map(([k, description]) => (
                <div key={k}>
                  <dt>
                    <Kbd>{k}</Kbd>
                  </dt>
                  <dd>{description}</dd>
                </div>
              ))}
            </dl>
          </details>
        </aside>
      </div>
    </div>
  );
}
