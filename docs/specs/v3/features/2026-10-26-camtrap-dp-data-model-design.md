# Camtrap DP data model

**Date:** 2026-10-26
**Status:** approved 2026-10-26
**Spec:** [v3 spec, "Data format"](../spec.md#data-format) · TODO: phase 0, "Camtrap DP data model"

## Goal

One data model, Camtrap DP 1.0.2, from the rig to the field app. The edge agent
writes a package folder per deployment, the field app stores the same tables in
SQLite, and exporting or uploading a deployment is copying its folder.

This note covers the tables, how ReefScanner's events and verdicts map onto
them, the sidecar table, and the database and migrations. The package writer
and reader, and switching the review UI over to these tables, are the next
TODO items; they are sketched here only as far as they constrain the model.

## Where the model lives

**One definition, in core.** `reefscanner.core.camtrap` defines the three
Camtrap tables and the sidecar as SQLModel classes, with field names exactly as
in the standard (`deploymentID`, `eventStart`, `bboxX`, …). SQLModel classes
work as plain validated objects without a database, so:

- the edge agent builds rows and writes CSVs with no database at all;
- the field app stores the very same classes in SQLite;
- the writer and reader serialise those classes, so there is one mapping to
  get right, not three.

This adds SQLModel (pydantic + SQLAlchemy, no web stack) to core. Both have
wheels for 64-bit ARM Linux, so it doesn't stand in the rig's way.

## Mapping ReefScanner onto Camtrap DP

### deployments: one row per rig drop

A deployment is one continuous recording session at one place: one rig drop,
or for laptop scans, one folder of footage from one site.

| Camtrap field | ReefScanner source |
|---|---|
| `deploymentID` | Set at deployment setup, e.g. `tofo-reef-2026-11-03-a` |
| `latitude`, `longitude` | Set at setup. **Required**, by the standard and by us: a good setup records them |
| `deploymentStart`, `deploymentEnd` | First and last recorded frame, with timezone |
| `locationName`, `cameraModel`, `cameraDepth`, `baitUse`, `habitat` | Set at setup, all optional |
| `cameraDepth` | Metres. For BRUVs this is the rig's water depth |
| `deploymentComments` | Free text |

Board, model and software versions go in the sidecar, not in `deployments`:
the standard has no field for them, and stuffing them into `deploymentTags`
would make them unsearchable.

### media: one row per file kept

| File | `captureMethod` | `fileMediatype` |
|---|---|---|
| Event clip | `activityDetection` | `video/mp4` |
| Clean peak frame | `activityDetection` | `image/jpeg` |
| Backup recording segment | `timeLapse` if time-lapse, else empty | `video/mp4` |

`timestamp` is the file's first frame. `filePath` is relative to the package
folder, and `filePublic` is `false`. Annotated thumbnails are derived files for
the review UI; they are not media.

### observations: machine and human, one row each per event

Each event gets **one machine observation**, and later **one human observation
once reviewed**. Both are media-level observations on the event's clean peak
frame, so both can carry a bounding box, and both name the event in `eventID`,
`eventStart` and `eventEnd`. Camtrap allows several classifications of the same
media, which is exactly this.

| Field | Machine row | Human row |
|---|---|---|
| `observationLevel` | `media` | `media` |
| `mediaID` | the peak frame | the peak frame |
| `eventID`, `eventStart`, `eventEnd` | the event | the event |
| `observationType` | `animal` | from the verdict, below |
| `scientificName` | from the detector class: `elasmobranch` → `Elasmobranchii` | the reviewer's species, as a scientific name |
| `bboxX/Y/Width/Height` | the detector's peak box, relative to frame size | the corrected box, else the detector's |
| `classificationMethod` | `machine` | `human` |
| `classifiedBy` | model name and version, e.g. `SharkTrack (ONNX, models-v1)` | reviewer's name |
| `classificationProbability` | peak confidence | empty |
| `classificationTimestamp` | when detected | when reviewed |

Verdicts become observation types:

A false positive splits in two: either nothing was there, or something other
than the target was, which the reviewer may name.

| Verdict | `observationType` | `scientificName` | `observationTags` |
|---|---|---|---|
| TP | `animal` | the species | `verdict:TP` |
| FP, nothing there | `blank` | empty | `verdict:FP` |
| FP, something else | `animal` | what it was, optional | `verdict:FP-other` |
| unsure | `unknown` | empty | `verdict:unsure` |
| not reviewed | no human row | | |

"Not reviewed" stays different from "unsure", as in v2. The tag keeps the
verdict explicit, since `animal` alone can't tell a TP from an FP-other.

**Later, with tracking:** one machine observation per track per event instead
of one per event, which the standard already allows. The model doesn't change.

### Sidecar: what Camtrap DP has no field for

Two extra resources with names outside Camtrap's reserved three, which keeps the
package valid:

- **`reefscanner-observations.csv`**, one row per observation, keyed by
  `observationID`: `trackID`, `modelName`, `modelVersion`, `detectorBackend`,
  `detectorConfig` (the scan config as JSON).
- **`reefscanner-detections.csv`**, one row per detection per sampled frame,
  keyed by `observationID`: `frameTimestamp`, box, `confidence`. This is the
  "detector confidence per frame" from the spec, and what the threshold
  recommendation and tracking will want.

Deployment-level extras (board, camera firmware, software version) go in the
`datapackage.json` under a `reefscanner` key, which the Frictionless spec permits.

### Package metadata

`datapackage.json` needs `created`, `contributors`, `project`, `spatial`,
`temporal` and `taxonomic`. The writer derives `spatial`, `temporal` and
`taxonomic` from the rows. `project` and `contributors` come from settings in
the field app; defaults: `samplingDesign: targeted`,
`captureMethod: [activityDetection]`, `individualAnimals: false`,
`observationLevel: [media]`.

## IDs

Readable and deterministic, so re-importing a package updates rows instead of
duplicating them:

- `mediaID`: `<deploymentID>/<eventID>/clip` and `.../frame`; backup segments
  `<deploymentID>/backup/<n>`
- `observationID`: `<eventID>/machine` and `<eventID>/human`
- `eventID`: `<deploymentID>/<video-stem>_<seq>`, the v2 event id made unique
  across deployments

## Database and migrations

- The Camtrap tables and sidecar join the app's database next to `Project` and
  `Job`. `Event` and `Label` stay until the review UI switches to observations
  (the "field app reads packages" item), then go.
- **Alembic from day one.** The first migration creates every table. The app
  runs `upgrade head` at startup, replacing today's `create_all` plus hand-made
  column patching.
- **Fresh database, no backward compatibility:** older databases, results CSVs
  and manifests are not read or migrated.
- Timestamps are stored timezone-aware and written with an offset, as the
  standard requires.

## Validation

Tests write a package and validate it against the Camtrap DP 1.0.2 profile and
table schemas, with copies of those files kept in the repo so tests never need
the network. The validator (`frictionless`) is a dev dependency only. The writer
itself checks the few rules that would otherwise fail later: required fields,
relative boxes in 0 to 1, timezone on every datetime.

## Builder's calls

These are mine; easy to change if they look wrong:

- Both observation kinds sit on the peak frame, rather than event-level human
  rows with no box. Keeps reviewed boxes usable as training data.
- `cameraDepth` holds the water depth, the closest standard field.
- Deterministic IDs as above, not UUIDs.
- The model lives in core, not the app.

## Decided

1. **Location** is required: a good setup records coordinates.
2. **Species** are stored as scientific names, following the standard. If that
   proves too hard to type, display names can be mapped onto them later.
3. **False positives** are split into "nothing there" and "something else",
   with an optional name for what it was.
