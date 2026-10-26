# ReefScanner v3 — On-Rig Live Detection

Oct 26, 2026 · @C

## Overview and scope

v3 is a functional prototype of on-rig live detection: a headless edge agent analyses footage underwater and keeps only the clips worth reviewing. The v2 desktop app stays as the review tool.

**Scope.** A prototype, not a deployment for one project. Volunteer work in Mozambique supplied the requirements, but the design does not depend on that rig. It assumes only that it runs underwater with power and a light source; board, camera, housing and power specifics are worked out later.

**Goals**

- Analyse footage live and save event clips with pre-roll, plus a backup recording as an audit trail.
- Stay agnostic to board and camera, with the capacity to analyse 24 to 30 fps.
- Keep it simple: leave seams for light control, tracking, species ID, connectivity and cloud, but build none of them now.
- Use one data format, Camtrap DP, from the rig to the field app.

**Unchanged from v1 and v2.** Recall over precision. A human gives the final verdict. The engine stays free of web dependencies.

**Non-goals for the prototype.** Specific hardware choices, light control, tracking and species ID, live connectivity, the cloud, individual re-identification.

**The prototype is done when** it runs unattended underwater with any supported camera, produces a valid data package, and its recall on replayed, labelled footage matches the v2 desktop scan.

## Assumptions and constraints

The prototype assumes it runs underwater in a sealed housing, with power and a light source available; nothing more specific. These constraints follow from that:

| Constraint | What it means for the design |
| --- | --- |
| Power is limited | Detection rate adapts; idle work stays cheap |
| Sealed housings trap heat | Handle thermal throttling; log frame-rate drops |
| Radio does not work underwater | Works fully offline; data comes off at the surface |
| Housings are opened rarely | Configure, test and sync over Wi-Fi or USB before sealing |
| A missed detection is lost for good | Keep a backup recording until the detector is trusted |
| Field laptops may be old | The field app runs offline on modest hardware |
| No network clock underwater | Sync the clock before each deployment; a real-time clock is recommended |

## Architecture

Three tiers share one core package: the rig decides what to keep, the field laptop is where humans review it, and a later cloud tier only pools finished packages.

&#91;embedded content: system architecture · 3 tiers on a shared core\]

The rig hands data to the field app at the surface; the dashed buoy link and the cloud are later extensions.

**Repo layout.** One monorepo:

- `core/`: event schema, Camtrap DP reader and writer, detector interface and backends. Today's `engine/` is most of it.
- `edge/`: the headless edge agent.
- `app/`: the v2 field app plus device sync.
- `cloud/`: later.

## Edge agent

The edge agent is a headless Python service that films, detects and writes clips; it runs only lightweight orchestration in Python, while frames stay in a native pipeline. It reuses the v2 engine's detector interface, event aggregation and clip logic.

**Modules**

1. **Camera adapter.** One interface over any camera: a GoPro (USB webcam mode or HDMI capture), USB webcams, board cameras, RTSP IP cameras, and video-file replay. It delivers a full-quality stream for recording and a low-res stream (about 640 px) for detection, scaled in hardware where the camera allows, otherwise in software.
2. **Ring buffer.** Holds the last N seconds of the encoded full-quality stream (default 30 s), so every clip includes the animal's approach.
3. **Scheduler.** Detects at 2 to 5 fps while idle and at full frame rate for a burst after a detection, then drops back.
4. **Detector.** Runs on the low-res stream behind the existing pluggable interface. SharkTrack stays the default model.
5. **Event writer.** Writes the clip (pre-roll + event + post-roll), a clean peak frame, an annotated thumbnail and the Camtrap DP rows.
6. **Backup recorder.** Continuous low-bitrate or time-lapse recording, so missed animals can still be found while the detector earns trust.
7. **Health.** Runs under systemd with a watchdog; logs temperature, storage and frame-rate drops.
8. **Status page.** Used before sealing: live preview with the detector overlay, health, configuration and clock sync.

**Extension points, not built now.** Tracker, species classifier on high-res crops, light control through a hardware output, power monitoring. Each plugs into the scheduler or event writer without touching the rest.

**Process model.** Capture and encoding run in a separate process from inference, and frames are shared without copies. At full frame rate the frame path is a native pipeline (for example GStreamer), so Python never touches pixels.

**Development without hardware.** The adapter's file-replay and webcam sources let the whole agent run on a laptop. Replaying labelled BRUV footage at real-time speed is the main simulator and test harness.

## Hardware requirements

No board or camera is assumed: the prototype targets any Linux board that meets these requirements, chosen later by benchmark.

- Sustain 30 fps of detection on the low-res stream, even if normal operation uses less.
- Encode the full-quality stream while detection runs.
- Run Linux and Python, and reach a camera through one of the adapter's sources.
- Stay stable in a sealed housing under thermal load.

**Backend abstraction.** The detector sits behind one interface with a backend per platform. A single trained model is exported per target (ONNX, then TensorRT, Hailo or RKNN), so switching boards means writing one backend.

## Data format

Every tier speaks [Camtrap DP](https://camtrap-dp.tdwg.org/): one `datapackage.json` metadata file plus three CSV tables. Each rig deployment writes one package folder, so export and cloud upload are just copying it.

| Table | One row per | ReefScanner content |
| --- | --- | --- |
| `deployments.csv` | Rig drop | Start, end, location, rig and camera setup, board and model version |
| `media.csv` | Media file | Event clips, clean peak frames, backup recording segments, as relative paths |
| `observations.csv` | Observation | One row per tracked animal per event: species, bounding box, classification method and confidence |

- **Bounding boxes** use four values from 0 to 1 relative to the image size ([FAQ](https://camtrap-dp.tdwg.org/faq/)), so they are independent of the low-res and high-res streams.
- **Extensions** (track ID, detector confidence per frame, model version per observation) live in a sidecar table keyed by observation ID, so the package itself stays valid Camtrap DP.
- **Internal storage** mirrors the same tables in SQLite through the existing ORM, which makes the later move to Postgres mostly configuration.
- **Human verdicts** from the review UI are written back as observations classified by a human, next to the machine ones.
- **Large tables** can be gzipped as `.csv.gz`, which the standard supports.

The v2 results CSV stays supported as a legacy import, so earlier runs are not orphaned.

## Field app

The v2 desktop app (FastAPI, SQLite, React, PyWebView) stays the review tool; v3 adds the rig as a data source. It keeps v2's offline, localhost-only posture.

- **Device.** Connect to an agent over Wi-Fi or USB, show its health, and pull its deployment packages. Import from an SD card or USB drive works the same way.
- **Deployment setup.** Before sealing: name the deployment, set the location, push the configuration and model version, sync the clock, and check the camera framing in the live preview.
- **Review.** Imported packages feed the existing review flow and keyboard shortcuts unchanged. Verdicts are written back into the package as human observations.
- **Laptop scanning** of recorded footage stays available as an option.

## Extensions (later)

The prototype leaves a seam for each of these but builds none of them.

| Extension | Plugs into | Notes |
| --- | --- | --- |
| Light control | Scheduler, through a hardware output | Dim while idle, brighten on an event; mainly for night use |
| Tracking and counting | Between detector and event writer | Track IDs land in the Camtrap DP sidecar table |
| Species ID | Event writer, on high-res crops | Second-stage classifier per track |
| Buoy link | Event writer to a network | Alerts over a low-power link; uploads and live view over a power-switched satellite link such as Starlink |
| Cloud | Field app export | Pools Camtrap DP packages from many sites; the first multi-user part |

## Roadmap

The prototype is done at the end of phase 2; the extensions follow afterwards, in any order.

&#91;embedded content: roadmap · 3 phases to a prototype, then extensions\]

Phases 0 and 1 need no water at all: replayed footage and any camera on a desk are enough.

## Open questions

- [ ] Which camera should the adapter support first: GoPro, USB webcam or a board camera?
- [ ] Which board should phase 1 benchmark first?
- [ ] Does the backup recording need full quality, for example for protocols that count animals over a fixed window?
- [ ] Licensing: Ultralytics YOLO is AGPL-3.0. Fine for research use; needs a decision before any wider distribution.
- [x] Does v3 live in the existing ReefScanner repo as a monorepo, or in a new one?

* Same repo -> the old version can be restructured

## Sources

- [Camtrap DP overview](https://camtrap-dp.tdwg.org/)
- [Camtrap DP FAQ: bounding boxes, compressed tables](https://camtrap-dp.tdwg.org/faq/)
- [SharkTrack paper](https://web3.arxiv.org/pdf/2407.20623)
- [ReefScanner v2 spec](../v2/spec.md) · [v1 spec](../v1/spec.md)
