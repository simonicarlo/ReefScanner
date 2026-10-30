import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import {
  invalidateProjects,
  keys,
  useEvents,
  useJob,
  useProject,
  useSaveReview,
  useSpecies,
} from "../lib/queries";
import type { ReefEvent, Verdict } from "../lib/types";
import { basename, clockTime, duration, eventLabel, localDate, score, timecode, timeOfDay } from "../lib/format";
import { useBackdrop } from "../lib/backdrop";
import { useToast } from "../lib/toast";
import { VERDICT_INFO, VERDICT_ORDER } from "../lib/verdicts";
import { BboxOverlay } from "../components/BboxOverlay";
import { Page } from "../components/Page";
import { Timeline } from "../components/Timeline";
import { VerdictSymbol } from "../components/VerdictSymbol";
import { Button, Empty, ErrorNote, Kbd, Spinner, cx } from "../components/ui";
import styles from "./EventReview.module.css";

const VIEWS = [
  { value: "clip", label: "Clip" },
  { value: "peak", label: "Peak frame" },
] as const;

/** Something known about one clip, kept with its URL so a new event's clip
 * never shows the last one's. */
interface ClipState<T> {
  url: string;
  value: T;
}

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
      invalidateProjects(queryClient);
    },
  });

  const [species, setSpecies] = useState("");
  const [notes, setNotes] = useState("");
  const [showBox, setShowBox] = useState(true);
  const [view, setView] = useState<"clip" | "peak">("clip");
  // The media's own shape (width / height), learned when it loads, so the
  // overlay's percentages land on the picture rather than on letterbox bars.
  const [aspect, setAspect] = useState(16 / 9);

  // The clip's length and playhead, learned from the video element.
  const [clipLength, setClipLength] = useState<ClipState<number> | null>(null);
  const [clipTime, setClipTime] = useState<ClipState<number> | null>(null);
  const [playing, setPlaying] = useState(false);
  // A seek asked for from the peak-frame view, applied once the clip loads.
  const pendingSeek = useRef<number | null>(null);

  const videoRef = useRef<HTMLVideoElement>(null);
  const speciesRef = useRef<HTMLInputElement>(null);

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

  // The playhead follows the video every frame while it plays; timeupdate
  // alone fires only a few times a second and the head would jump.
  const clipUrl = event?.clip_url ?? "";
  useEffect(() => {
    if (!playing) return;
    let frame = 0;
    const follow = () => {
      const video = videoRef.current;
      if (video) setClipTime({ url: clipUrl, value: video.currentTime });
      frame = requestAnimationFrame(follow);
    };
    frame = requestAnimationFrame(follow);
    return () => cancelAnimationFrame(frame);
  }, [playing, clipUrl]);

  const seek = useCallback(
    (clipSeconds: number) => {
      const video = videoRef.current;
      if (view === "clip" && video) {
        video.currentTime = clipSeconds;
        setClipTime({ url: clipUrl, value: clipSeconds });
      } else {
        // The peak frame has no video to seek: show the clip, then seek.
        pendingSeek.current = clipSeconds;
        setView("clip");
      }
    },
    [view, clipUrl],
  );

  const togglePlay = useCallback(() => {
    const video = videoRef.current;
    if (view !== "clip" || !video) {
      setView("clip");
      return;
    }
    if (video.paused) void video.play();
    else video.pause();
  }, [view]);

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
        case " ":
          e.preventDefault();
          togglePlay();
          break;
      }
    };

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [record, goTo, previous, next, event?.review?.verdict, togglePlay]);

  if (isLoading)
    return (
      <Page>
        <Spinner label="Loading event" />
      </Page>
    );
  if (!event)
    return (
      <Page>
        <Empty title="Event not found" />
      </Page>
    );

  const verdict = event.review?.verdict;
  const reviewedBox = event.review?.bbox ?? null;
  // Dashed when the reviewer's box differs from the detector's.
  const corrected =
    reviewedBox !== null && JSON.stringify(reviewedBox) !== JSON.stringify(event.bbox);
  const reviewedCount = siblings.filter((e) => e.review).length;

  const clipStart = event.clip_start_seconds;
  // Before the clip has loaded (or on the peak frame), its length follows from
  // the padding: as much after the event as before it.
  const length =
    clipLength?.url === event.clip_url
      ? clipLength.value
      : clipStart !== null
        ? event.end_seconds - clipStart + (event.start_seconds - clipStart)
        : null;
  const playhead =
    view === "peak"
      ? clipStart !== null
        ? event.peak_seconds - clipStart
        : null
      : clipTime?.url === event.clip_url
        ? clipTime.value
        : 0;

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
            {project ? `${project.name} · ` : ""}Run #{jid} · {reviewedCount} of{" "}
            {siblings.length} reviewed
          </span>
        </div>

        <div className={styles.tools}>
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
                    if (Number.isFinite(v.duration)) {
                      setClipLength({ url: event.clip_url, value: v.duration });
                    }
                    if (pendingSeek.current !== null) {
                      v.currentTime = pendingSeek.current;
                      pendingSeek.current = null;
                    }
                  }}
                  onTimeUpdate={(e) => {
                    const v = e.currentTarget;
                    setClipTime({ url: event.clip_url, value: v.currentTime });
                  }}
                  onPlay={() => setPlaying(true)}
                  onPause={() => setPlaying(false)}
                  onClick={togglePlay}
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
          <div className={styles.controls}>
            <div className={styles.controlRow}>
              <button
                type="button"
                className={styles.play}
                onClick={togglePlay}
                aria-label={view === "clip" && playing ? "Pause" : "Play"}
              >
                <svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
                  {view === "clip" && playing ? (
                    <path d="M4.5 3h2.2v10H4.5zM9.3 3h2.2v10H9.3z" />
                  ) : (
                    <path d="M5 3.2v9.6c0 .4.4.6.7.4l7.4-4.8a.5.5 0 0 0 0-.8L5.7 2.8c-.3-.2-.7 0-.7.4z" />
                  )}
                </svg>
              </button>
              <div className={styles.tabs} role="group" aria-label="Show">
                {VIEWS.map((v) => (
                  <button
                    key={v.value}
                    type="button"
                    className={styles.tab}
                    aria-pressed={view === v.value}
                    onClick={() => setView(v.value)}
                  >
                    {v.label}
                  </button>
                ))}
              </div>
              <button
                type="button"
                className={styles.tab}
                aria-pressed={showBox}
                onClick={() => setShowBox((v) => !v)}
                title="The box marks the peak frame. On the clip it shows where to look, not where the animal goes."
              >
                Box {showBox ? "on" : "off"} <Kbd>B</Kbd>
              </button>
            </div>
            <Timeline
              clipStart={clipStart}
              duration={length}
              current={playhead}
              start={event.start_seconds}
              end={event.end_seconds}
              peak={event.peak_seconds}
              onSeek={seek}
            />
          </div>
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

      <section className={styles.events} aria-label="Events in this run">
        <div className={cx(styles.eventRow, styles.eventHead)} aria-hidden="true">
          <span>Start</span>
          <span>Source video</span>
          <span className={styles.right}>Length</span>
          <span className={styles.right}>Score</span>
          <span>Verdict</span>
        </div>
        {siblings.map((e) => {
          const current = e.id === eid;
          const v = e.review?.verdict;
          return (
            <Link
              key={e.id}
              to={`/jobs/${jid}/events/${encodeURIComponent(e.id)}`}
              className={styles.eventRow}
              aria-current={current ? "page" : undefined}
            >
              <span className={styles.num}>{timeOfDay(e.start_time)}</span>
              <span className={styles.source} title={e.source_video}>
                {basename(e.source_video)}
              </span>
              <span className={cx(styles.num, styles.right)}>{duration(e.duration_seconds)}</span>
              <span className={cx(styles.num, styles.right)}>{score(e.confidence, 3)}</span>
              <span className={cx(styles.verdictCell, !v && styles.unreviewed)}>
                <span
                  className={cx(styles.dot, v && styles.judged)}
                  style={v ? { background: VERDICT_INFO[v].color } : undefined}
                />
                {v ? VERDICT_INFO[v].label : "Not reviewed"}
              </span>
            </Link>
          );
        })}
      </section>
    </div>
  );
}
