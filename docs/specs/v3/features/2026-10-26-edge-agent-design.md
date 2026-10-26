# The edge agent, phase 0

**Date:** 2026-10-26
**Status:** built 2026-10-26
**Builds on:** [app on Camtrap DP](2026-10-26-app-on-camtrap-design.md)

## Goal

The whole agent runs on a laptop: a camera source feeds a ring buffer and a
scheduler, the detector runs on the frames the scheduler asks for, and every
event becomes a clip, a clean peak frame, an annotated thumbnail and Camtrap DP
rows in one package folder. A replay simulator drives it with recorded footage
and diffs its events against a laptop scan of the same files. That diff is the
phase 0 gate.

Phase 0 is plain Python and OpenCV. The native frame pipeline (GStreamer,
separate processes, zero-copy) is phase 1; the module seams here are the ones
it will slot into.

## Modules (`edge/src/reefscanner/edge/`)

| Module | Does |
| --- | --- |
| `camera.py` | `Source` interface: yields frames with a stream index and time. `FileReplay` (one or more files as one continuous stream, paced at real time or as fast as the agent takes them) and `Webcam` (OpenCV device). |
| `ringbuffer.py` | Encodes the full-quality stream with ffmpeg into short MPEG-TS segments and keeps only the last N seconds, plus whatever an open event still needs. Cuts clips by joining segments. |
| `scheduler.py` | Idle rate (default 2 fps) until a detection, then a burst at full frame rate until `burst_seconds` pass without one. Pure logic, driven by stream time. |
| `tracker.py` | Online event aggregation: collects candidates, closes an event once no detection has come for `merge_gap_seconds`, then reuses core's `aggregate_events` so events are built exactly as the laptop scan builds them. |
| `writer.py` | Per closed event: waits for the post-roll, writes the clip, clean frame and thumbnail, adds the rows (core's `rows_for_video`), and rewrites the package. |
| `agent.py` | Wires them together: a capture thread and a detection thread, plus a writer thread. |
| `replay.py`, `cli.py` | The simulator and the `reefscanner-edge` command (`run`, `replay`). |

## Decisions

### 1. The ring buffer is encoded segments on disk

The spec wants the *encoded* stream buffered, because 30 s of raw 1080p is
about 5 GB. ffmpeg's segment muxer writes 2 s MPEG-TS pieces with a forced
keyframe at every boundary, so a clip is a lossless join of whole segments,
with no re-encode. The cost is that clip edges snap to segment boundaries
(up to 2 s of extra pre-roll and post-roll), which only helps recall. On the board the
buffer folder goes on tmpfs, and GStreamer's `splitmuxsink` gives the same
segments in phase 1. The backup recorder (phase 1) is the same segment stream
with the deletion switched off.

*Alternative:* keep decoded frames in memory. Simplest, but it doesn't fit
in memory at full quality, and it isn't what the board will do.

### 2. Two pacing modes

- **Real time** (`--speed 1`, and always for a webcam): the source runs at
  its frame rate whether or not detection keeps up. A frame the detector is
  still busy for is dropped and counted, which is exactly the behaviour to
  measure.
- **Lockstep** (`--speed 0`): the source waits for the detector, so every
  frame the scheduler wants gets detected. The result is deterministic, and it
  is what the gate compares.

### 3. Detection on a low-res frame by default

The adapter hands the detector a copy scaled to 640 px wide, as the board's
low-res stream will be, and boxes are scaled back to full size. The laptop scan
passes the full frame and lets the model's letterbox shrink it, so the two can
differ slightly in confidence. The replay reports any difference, and
`--detect-width 0` turns the scaling off to match the laptop scan exactly.

### 4. The package is always valid on disk

After every event, the writer rewrites the whole package (the tables are small)
with `deploymentEnd` set to now, through the atomic `write_package`. A power cut
leaves a valid package of every event written so far. Clips go to `clips/`,
frames to `frames/` and thumbnails to `thumbnails/`, at the paths the media
rows name, as in the app's scan folders.

### 5. Time

A live camera's stream starts at the system clock (UTC, synced before the drop)
and is given in the deployment's `camera_timezone`. A replay starts at the first
file's recorded time, read with the project's `camera_timezone` and
`camera_clock` exactly as the laptop scan does, so both give the same
timestamps. Frame times are `index / fps` (constant frame rate). That is fine
for files and good enough for webcams in phase 0.

### 6. The gate diff

The replay runs core's laptop scan on the same files (same detector, same
settings) and matches events per file by time overlap. It reports matched
events, v2 events the agent missed (the gate: there must be none), extra agent
events, and dropped frames. The agent treats the files as one stream, so an
event spanning a file boundary is attributed to the file it starts in.

## Configuration

One YAML file: a `deployment` block (ID, latitude, longitude, camera timezone
and clock, optional depth, bait and comments), `project` (title, contributors),
`agent` (pre-roll 30 s, post-roll, idle fps, burst seconds, segment seconds,
detect width, buffer folder), and `detector`, which is a plain
`ReefScannerConfig` (detector, backend, weights, threshold, merge gap, minimum
event length), so the agent and the laptop scan read the same settings.

## Notes from building it

- **Idle frames stay on a fixed grid** (`index % stride == 0`) through bursts.
  With an idle rate that is a multiple of the laptop scan's sample rate (2 vs
  1 fps by default), the agent detects on every frame the scan does, and more.
- **Events can merge.** The agent sees an animal through gaps that the scan's
  sparser samples break into two events. The diff therefore matches by
  overlap, and an agent event may cover several scan events.
- **Gate result** on the four test dives (SharkTrack ONNX, lockstep): all 7
  scan events found, nothing missed and nothing extra, with both
  `--detect-width 0` and 640. In real time on the dev laptop, 12 of 853 frames were
  dropped during bursts, and both events were still found.
- Core gained `find_events` (the laptop scan without writing anything),
  `rows_for_event` (the per-event half of `rows_for_video`) and `file_start`.

## Out of scope

Separate processes and zero-copy frames, hardware encoding, and the backup
recorder (all phase 1). Health, systemd and thermal adaptation are also phase 1.
GoPro, RTSP and board camera sources come once the first camera is chosen.
