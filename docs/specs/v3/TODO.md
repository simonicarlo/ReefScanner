# v3 TODO

Tracks the work in [spec.md](spec.md), grouped by the roadmap's phases. Each
phase ends at a gate; don't start the next phase's hardware work until the gate
holds. Feature specs and plans for any item go in [`features/`](features/).

## Decisions

- **Deployments** last up to 24 h today; longer is the goal. Size storage and
  power for 24 h first, without designing anything that caps it there.
- **Recall over precision**, as before. An extra false-positive clip is cheap;
  a missed event is lost for good.
- **Packaging:** one uv workspace with separate packages for `core`, `edge` and
  `app`, so the rig never installs the web stack and the laptop never installs
  board runtimes.
- **Detector runtime:** ONNX Runtime is the default backend everywhere (CPU,
  CUDA or TensorRT when present; CoreML on request, as it was slower on an M2).
  Ultralytics is an optional backend kept for training, export, SAHI, and as
  the reference to check ONNX output against. Board backends (TensorRT, Hailo,
  RKNN) all start from the same ONNX export.
- **ONNX input shape:** the laptop export is dynamic, padding frames only to a
  multiple of 32 as Ultralytics does with a `.pt`; that is what makes ONNX
  match v2 exactly. Boards that need a fixed shape get `export-onnx --static`,
  ideally at the camera's aspect ratio rather than a square, since padding to a
  square changed confidences by ~0.09 on average and found extra boxes.
- **No backward compatibility.** Nothing from v1 or v2 is imported or
  migrated: no results CSVs, databases or manifests.
- **Database:** start fresh. Tables mirror Camtrap DP
  through the ORM (SQLModel, as in v2), with Alembic migrations from day one.
- **Hardware:** development targets a laptop; specific boards come later and
  only by benchmark.
- **No test bench yet.** Build the prototype as well as we can, then test and
  optimise against real deployments. Until then, "same events as v2" means
  comparing against the v2 scan of the same footage, which needs no labels.
- **Time comes from the person, not the file.** Video files can't be trusted
  about their timezone: GoPros record local time labelled as UTC, phones record
  real UTC. Every project says which zone the camera was in
  (`camera_timezone`, pre-filled with the laptop's and confirmed by the user)
  and what the file's clock holds (`camera_clock`: `local` or `utc`). Without
  a zone, timestamps stay blank rather than guessed. The zone is required even
  for UTC clocks: local time of day matters for the research, and UTC alone
  doesn't give it. The rig will need the same
  two answers at deployment setup, next to clock sync.
- **Backup recording quality is configurable.** It defaults to full quality,
  because early deployments will keep all footage and be checked by hand; it
  can be reduced once researchers trust the detector.

## Phase 0 · Core refactor

Gate: replayed footage gives the same events as the v2 desktop scan.

- [x] Monorepo: uv workspace with `core/`, `edge/`, `app/`; move `engine/` into
      `core/`; CLI and existing tests keep working
- [x] Split dependencies: torch and Ultralytics out of `core`, detector backends
      as optional extras
- [x] ONNX export of SharkTrack and an ONNX Runtime backend (letterbox, decode,
      NMS); test that its detections match the Ultralytics backend. Identical on
      the four test dives: 72/72 detections, same 7 events as v2
- [x] Host `sharktrack.onnx` as a GitHub release asset (`models-v1`) so an
      install without Ultralytics can fetch it; downloads are hash-checked
- [ ] SAHI tiling for the ONNX backend (it needs Ultralytics today)
- [x] Camtrap DP data model: SQLModel tables for deployments, media and
      observations, the extension sidecar table, and Alembic set up
      ([design](features/2026-10-26-camtrap-dp-data-model-design.md))
- [x] Camtrap DP writer and reader, validated against the official schema; one
      package folder per deployment
- [ ] Camera adapter interface, with file replay at real-time speed and USB
      webcam sources
- [ ] Ring buffer of the encoded full-quality stream (default 30 s pre-roll)
- [ ] Scheduler: 2–5 fps while idle, full frame rate in a burst after a
      detection, then back to idle
- [ ] Event writer: clip (pre-roll + event + post-roll), clean peak frame,
      annotated thumbnail, Camtrap DP rows
- [ ] Replay simulator: run the whole agent on a laptop against the baseline
      footage, write a package, and diff its events against the v2 reference
- [ ] Field app reads Camtrap DP packages and feeds them into the existing review
      flow; verdicts written back as human observations

## Phase 1 · Bench prototype

Gate: 30 fps detection capacity sustained on the chosen board.

- [ ] Board shortlist and a benchmark script: detection fps on the low-res
      stream while encoding full quality, over a long run, with temperature
      logged
- [ ] Native frame pipeline (e.g. GStreamer): full-quality and low-res streams,
      capture and inference in separate processes, frames shared without copies
- [ ] Detector backend for the chosen board (TensorRT, Hailo or RKNN), from a
      static export at the camera's aspect ratio
- [ ] Backup recorder: continuous recording in segments; quality configurable
      (full quality by default, or low bitrate or time-lapse)
- [ ] Health: systemd unit, watchdog, logs of temperature, storage and frame-rate
      drops; adapts the detection rate under thermal throttling
- [ ] Agent on the board with a real camera, in air and then in a tank

## Phase 2 · Underwater prototype

Gate: an unattended run yields a valid package; recall checked against the backup.

- [ ] Status page on the rig: live preview with detector overlay, health,
      configuration, clock sync
- [ ] Field app, device: connect over Wi-Fi or USB, show health, pull packages;
      import from an SD card or USB drive the same way
- [ ] Field app, deployment setup: name, location, camera timezone and clock
      kind, push config and model version, sync the clock, check framing in
      the live preview
- [ ] Recall check tool: compare a deployment's events against a human pass over
      its backup recording
- [ ] Sealed housing, unattended run, acceptance check

## Open questions

- [ ] Which camera should the adapter support first: GoPro, USB webcam or a board
      camera?
- [ ] Which board should phase 1 benchmark first?
- [ ] Licensing: Ultralytics YOLO is AGPL-3.0. Running the exported ONNX model
      through ONNX Runtime keeps Ultralytics code off the rig, but the
      license question for training and distribution still needs a decision.
- [ ] Storage: full-quality backup for 24 h is roughly 130 GB at 1080p and
      12 Mbit/s, so the rig needs a 256 GB card or larger. Confirm when the
      camera is chosen.
