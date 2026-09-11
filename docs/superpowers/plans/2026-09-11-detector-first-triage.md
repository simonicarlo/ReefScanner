# Detector-First Triage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove motion as a recall source, turn TP/FP/unsure labels into a confidence-threshold recommendation, and export clean training frames alongside annotated thumbnails.

**Architecture:** The threshold sweep is a pure function over `(confidence, verdict)` pairs in `app/analysis.py`, so it is testable with no database and no video. The engine loses its motion-only branch but keeps `MotionGate` for prefiltering and future tracking. A minimal startup migration adds nullable columns so existing labels survive the new `frame_path` field.

**Tech Stack:** Python 3.11, FastAPI, SQLModel/SQLite, Ultralytics YOLO, React 19 + TypeScript + Tailwind v4, pytest.

**Spec:** `docs/superpowers/specs/2026-09-11-detector-first-triage-design.md`

**Run tests with:** `uv run pytest` (the venv needs `uv sync --extra desktop --extra ml --extra dev`).

---

## File Structure

| File | Responsibility |
|---|---|
| `src/reefscanner/app/analysis.py` | **New.** Pure threshold-sweep logic. No DB, no I/O. |
| `src/reefscanner/app/routers/analysis.py` | **New.** `GET /api/jobs/{id}/threshold-analysis`. |
| `src/reefscanner/engine/config.py` | Drop `DETECTOR_NONE`, default to `marine`, add `frames_dirname`. |
| `src/reefscanner/engine/detectors/none_detector.py` | **Delete.** |
| `src/reefscanner/engine/pipeline.py` | Drop the motion-only branch; write both images. |
| `src/reefscanner/engine/clips.py` | Split frame reading from frame writing. |
| `src/reefscanner/app/db.py` | Add-missing-nullable-columns migration. |
| `src/reefscanner/app/models.py` | `Event.frame_path`. |
| `tests/conftest.py` | Host the shared `StubDetector`. |
| `frontend/src/components/ThresholdPanel.tsx` | **New.** The sweep table + Apply button. |

---

## Task 1: Share the stub detector

Pipeline tests currently run motion-only end to end. They must move to a stub detector *before* motion-only is removed, or the suite breaks mid-plan. This task only moves existing code.

**Files:**
- Modify: `tests/conftest.py`
- Modify: `tests/test_detector.py`

- [ ] **Step 1: Move the stub into conftest**

Append to `tests/conftest.py`:

```python
class StubDetector:
    """Stand-in detector: flags large bright blobs as 'shark'.

    Lets pipeline tests exercise the real detector code path without model
    weights, a download, or GPU time. The synthetic 'animal' is a bright
    rectangle, so a brightness threshold plus an area floor finds exactly it.
    """

    name = "stub"
    class_names = ["shark"]

    def __init__(self, confidence: float = 0.9, min_area: int = 1000):
        self.confidence = confidence
        self.min_area = min_area

    def detect(self, frame):
        from reefscanner.engine.detection import Detection

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
        contours, _ = cv2.findContours(
            thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        return [
            Detection(
                bbox=cv2.boundingRect(c),
                class_name="shark",
                confidence=self.confidence,
            )
            for c in contours
            if cv2.contourArea(c) >= self.min_area
        ]


@pytest.fixture
def stub_detector(monkeypatch):
    """Patch the pipeline's detector factory to return the stub.

    The same instance is both patched in and returned, so a test can configure
    it (confidence, min_area) and have the pipeline actually use those values.
    Returning a second instance would make such a test pass while exercising
    nothing.
    """
    import reefscanner.engine.pipeline as pipeline

    detector = StubDetector()
    monkeypatch.setattr(pipeline, "get_detector", lambda cfg: detector)
    return detector
```

- [ ] **Step 2: Point test_detector.py at the shared stub**

In `tests/test_detector.py`, delete the local `StubSharkDetector` class and change the import line:

```python
from conftest import StubDetector, make_video
```

Then replace both occurrences of `StubSharkDetector()` with `StubDetector()`.

- [ ] **Step 3: Run the tests**

Run: `uv run pytest tests/test_detector.py -v`
Expected: PASS (same tests, same behaviour, stub now shared).

- [ ] **Step 4: Commit**

```bash
git add tests/conftest.py tests/test_detector.py
git commit -m "test: share the stub detector via conftest"
```

---

## Task 2: Move pipeline tests onto the stub detector

**Files:**
- Modify: `tests/test_pipeline.py`

- [ ] **Step 1: Switch the shared config helper to a detector**

In `tests/test_pipeline.py`, change `_cfg` so every pipeline test runs in detector mode:

```python
def _cfg(input_dir: Path, output_dir: Path, **over) -> ReefScannerConfig:
    base = dict(
        input_folder=str(input_dir),
        output_folder=str(output_dir),
        frame_sample_fps=2.0,
        warmup_frames=3,
        min_blob_area=300,
        persistence_frames=2,
        merge_gap_seconds=3.0,
        min_event_seconds=1.0,
        pad_seconds=1.0,
        # Detector mode: get_detector is patched to the stub by the
        # stub_detector fixture, so no weights are ever loaded.
        detector="generic",
    )
    base.update(over)
    return ReefScannerConfig(**base)
```

- [ ] **Step 2: Add the fixture to every test in the file**

Every test function in `tests/test_pipeline.py` that calls `process_folder` gains `stub_detector` as its first parameter. For example:

```python
def test_end_to_end_produces_csv_clips_thumbnails(stub_detector, input_dir, output_dir):
```

Apply the same change to: `test_event_ids_unique_across_batch`,
`test_resume_skips_completed_videos`, `test_no_events_when_no_animal`,
`test_fp_report_counts_labels`, `test_on_frame_reports_progress_within_a_video`,
`test_should_cancel_stops_the_run`, `test_cancelled_video_is_not_marked_complete`,
`test_changing_settings_reprocesses_instead_of_skipping`,
`test_output_paths_do_not_invalidate_the_manifest`, and
`test_pre_v2_manifest_entries_are_reprocessed`.

(Run `uv run pytest tests/test_pipeline.py --collect-only -q` to list the exact
names present, in case the file has drifted.)

- [ ] **Step 3: Delete the obsolete no-torch test**

Remove `test_detector_none_imports_no_torch` entirely — it asserts a guarantee
that ceases to exist when motion-only is removed. Also remove the now-unused
`subprocess`, `sys` and `textwrap` imports at the top of the file if nothing else
uses them.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_pipeline.py -v`
Expected: PASS. `test_no_events_when_no_animal` still passes because the stub
finds no bright blobs in animal-free footage.

- [ ] **Step 5: Commit**

```bash
git add tests/test_pipeline.py
git commit -m "test: run pipeline tests through a stub detector"
```

---

## Task 3: Remove motion as a recall source

**Files:**
- Delete: `src/reefscanner/engine/detectors/none_detector.py`
- Modify: `src/reefscanner/engine/config.py`
- Modify: `src/reefscanner/engine/detectors/__init__.py`
- Modify: `src/reefscanner/engine/pipeline.py`
- Modify: `src/reefscanner/engine/__init__.py`, `src/reefscanner/__init__.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_config.py`, replace `test_get_detector_none_finds_nothing` and
`test_marine_with_weights_needs_ultralytics` with:

```python
def test_detector_defaults_to_marine():
    """A detector-first tool must not default to something that finds nothing."""
    assert ReefScannerConfig().detector == "marine"


def test_none_detector_is_gone():
    """Motion-only was removed; asking for it must fail loudly, not silently."""
    with pytest.raises(ValueError, match="detector must be one of"):
        ReefScannerConfig(detector="none")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_config.py::test_none_detector_is_gone -v`
Expected: FAIL — `detector="none"` is currently valid, so no `ValueError` is raised.

- [ ] **Step 3: Update the config**

In `src/reefscanner/engine/config.py`, replace the detector constants block:

```python
# Detector names recognised by the pluggable detector interface.
#
# Motion-only recall (the old ``none``) was removed: on real footage the motion
# gate cannot separate a small fish close to the camera from a large animal far
# away, because monocular video carries no depth cue. ``MotionGate`` survives as
# an optional pre-filter, not as the thing that decides what matters.
DETECTOR_GENERIC = "generic"
DETECTOR_MARINE = "marine"
VALID_DETECTORS = (DETECTOR_MARINE, DETECTOR_GENERIC)
```

Change the field default:

```python
    detector: str = DETECTOR_MARINE
```

Update the comment above it:

```python
    #: marine = SharkTrack YOLO (the default; trained on real BRUVS footage);
    #: generic = stock COCO YOLO objectness (experimental).
```

- [ ] **Step 4: Update the detector factory**

In `src/reefscanner/engine/detectors/__init__.py`, rewrite the imports and body:

```python
"""Detector factory.

Only the selected detector's dependencies are imported, so building a config
never costs a torch import until a detector is actually constructed.
"""

from __future__ import annotations

from ..config import DETECTOR_GENERIC, DETECTOR_MARINE, ReefScannerConfig
from .base import Detector

__all__ = ["Detector", "get_detector"]


def get_detector(cfg: ReefScannerConfig) -> Detector:
    name = cfg.detector
    if name == DETECTOR_MARINE:
        from .marine_detector import build_marine

        return build_marine(cfg)
    if name == DETECTOR_GENERIC:
        from .generic_detector import build_generic

        return build_generic(cfg)
    raise ValueError(f"Unknown detector: {name!r}")
```

- [ ] **Step 5: Delete the none detector and the motion-only branch**

```bash
git rm src/reefscanner/engine/detectors/none_detector.py
```

In `src/reefscanner/engine/pipeline.py`, delete the `DETECTOR_NONE` import and
replace the whole motion-only block inside `_collect_candidates` — that is, these lines:

```python
    candidates: list[Candidate] = []

    if cfg.detector == DETECTOR_NONE:
        # v1 motion-only: the gate is the recall source.
        gate = MotionGate(cfg)
        for sample in iter_sampled_frames(info, cfg.frame_sample_fps):
            cand = gate.process(sample)
            if cand is not None:
                candidates.append(cand)
            _tick(sample)
        return candidates

    # v2 detector-scans-frames: the detector is the recall source.
```

with:

```python
    candidates: list[Candidate] = []

    # The detector is the recall source. Motion is only ever an optional cheap
    # pre-skip of dead-static frames.
```

Change the import line at the top of the file from:

```python
from .config import DETECTOR_NONE, ReefScannerConfig
```

to:

```python
from .config import ReefScannerConfig
```

- [ ] **Step 6: Drop the re-exports**

In both `src/reefscanner/engine/__init__.py` and `src/reefscanner/__init__.py`,
remove `DETECTOR_NONE` from the import block and from `__all__`.

- [ ] **Step 7: Update the module docstring**

In `src/reefscanner/engine/pipeline.py`, replace the "Two modes" paragraph of the
module docstring with:

```
The detector scans every sampled frame and is the recall source; motion is an
optional cheap pre-skip (``motion_prefilter``).
```

- [ ] **Step 8: Run the full suite**

Run: `uv run pytest -v`
Expected: PASS. If a test still passes `detector="none"`, update it to `"generic"`.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat: remove motion as a recall source

On real footage the motion gate cannot separate a small fish close to the
camera from a large animal far away -- monocular video has no depth cue, so
min_blob_area is a proxy for distance the data does not support.

MotionGate stays as the optional pre-filter and as the basis for tracking
detected animals later. What goes is motion deciding what matters."
```

---

## Task 4: Make ML dependencies standard

**Files:**
- Modify: `pyproject.toml`
- Modify: `README.md`

- [ ] **Step 1: Fold the ml extra into the base dependencies**

In `pyproject.toml`, move the ML packages into `dependencies` and leave `ml` as a
back-compatible alias:

```toml
dependencies = [
    "opencv-python-headless>=4.9,<5",
    "numpy>=1.24,<3",
    "pandas>=2.0,<4",
    "tqdm>=4.65,<5",
    "PyYAML>=6.0,<7",
    # The detector is no longer optional: motion-only recall was removed, so an
    # install without these can't scan anything. NOTE: Ultralytics YOLO is
    # AGPL-3.0 (copyleft, network clause) -- fine for research and internal use;
    # see docs/model-research.md before distributing.
    "ultralytics>=8.1,<9",
    "torch>=2.0",
    # SharkTrack's checkpoint was saved by an older Ultralytics and needs dill to
    # unpickle. Ultralytics would try to pip-install it at load time, which fails
    # in any venv without pip.
    "dill>=0.3",
]
```

Replace the `ml` extra with:

```toml
# Kept so `pip install 'reefscanner[ml]'` keeps working; these are core now.
ml = ["sahi>=0.11"]   # tiled inference for distant/small animals (MIT)
```

- [ ] **Step 2: Update the README extras table**

In `README.md`, change the `[ml]` row of the extras table to:

```
| `[ml]` | SAHI tiled inference for small/distant animals |
```

and replace the sentence beginning "`pip install reefscanner` with no extras" with:

```
The YOLO detectors are core, not optional — motion-only triage was removed
because it cannot tell a small fish nearby from a large one far away.
```

Then remove the `uv sync --extra desktop --extra ml` line from the SharkTrack
section, since the detector now installs by default.

- [ ] **Step 3: Verify a clean resolve**

Run: `uv sync --extra desktop --extra dev && uv run python -c "import torch, ultralytics; print('ml is core')"`
Expected: prints `ml is core`.

- [ ] **Step 4: Run the suite**

Run: `uv run pytest`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml README.md
git commit -m "feat: make the YOLO detector a core dependency"
```

---

## Task 5: Threshold sweep logic

**Files:**
- Create: `src/reefscanner/app/analysis.py`
- Create: `tests/test_analysis.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_analysis.py`:

```python
"""Threshold sweep logic — pure, so no database or video is involved."""

from __future__ import annotations

from reefscanner.app.analysis import analyse_thresholds


def test_recommends_highest_threshold_that_keeps_every_confirmed():
    """The rule: never lose a real animal to save review time."""
    result = analyse_thresholds(
        [(0.9, "TP"), (0.5, "TP"), (0.32, "TP"), (0.25, "FP"), (0.21, "FP")],
        scan_threshold=0.2,
        min_labeled=1,
    )
    assert result.recommended == 0.32
    assert result.confirmed == 3
    assert result.rejected == 2


def test_sweep_points_are_the_observed_confidences():
    """Only the values where the answer changes — no arbitrary bins."""
    result = analyse_thresholds(
        [(0.9, "TP"), (0.4, "FP")], scan_threshold=0.2, min_labeled=1
    )
    assert [p.threshold for p in result.points] == [0.4, 0.9]


def test_point_counts_and_precision():
    result = analyse_thresholds(
        [(0.8, "TP"), (0.6, "FP"), (0.4, "TP")], scan_threshold=0.2, min_labeled=1
    )
    at_lowest = result.points[0]
    assert at_lowest.threshold == 0.4
    assert at_lowest.kept == 3
    assert at_lowest.confirmed_kept == 2
    assert at_lowest.rejected_kept == 1
    assert at_lowest.confirmed_lost == 0
    assert round(at_lowest.precision, 3) == 0.667

    at_highest = result.points[-1]
    assert at_highest.threshold == 0.8
    assert at_highest.kept == 1
    assert at_highest.confirmed_lost == 1
    assert at_highest.precision == 1.0


def test_unsure_is_neither_confirmed_nor_rejected():
    """A verdict a human couldn't reach is not evidence either way."""
    result = analyse_thresholds(
        [(0.9, "TP"), (0.5, "unsure"), (0.3, "FP")],
        scan_threshold=0.2,
        min_labeled=1,
    )
    assert result.undecided == 1
    assert result.confirmed == 1
    assert result.rejected == 1
    # 0.5 must not appear as a sweep point; it carries no evidence.
    assert [p.threshold for p in result.points] == [0.3, 0.9]


def test_no_confirmed_events_gives_no_recommendation():
    """Otherwise the rule is vacuous and 'recommends' discarding everything."""
    result = analyse_thresholds(
        [(0.9, "FP"), (0.4, "FP")], scan_threshold=0.2, min_labeled=1
    )
    assert result.recommended is None
    assert "No confirmed animals" in result.recommendation


def test_events_without_confidence_are_counted_not_swept():
    """Motion-era events have no confidence and can't be in a confidence sweep."""
    result = analyse_thresholds(
        [(None, "TP"), (None, "FP"), (0.7, "TP")],
        scan_threshold=0.2,
        min_labeled=1,
    )
    assert result.unscored == 2
    assert result.confirmed == 1
    assert [p.threshold for p in result.points] == [0.7]


def test_all_unscored_gives_no_recommendation():
    result = analyse_thresholds([(None, "TP"), (None, "FP")], min_labeled=1)
    assert result.recommended is None
    assert "no confidence" in result.recommendation.lower()


def test_no_labels_at_all():
    result = analyse_thresholds([])
    assert result.labeled == 0
    assert result.points == []
    assert result.recommended is None
    assert result.reliable is False


def test_reliability_threshold():
    """Few labels still compute, but must not masquerade as evidence."""
    sparse = analyse_thresholds([(0.9, "TP"), (0.3, "FP")], min_labeled=5)
    assert sparse.reliable is False

    plenty = analyse_thresholds(
        [(0.9, "TP"), (0.8, "TP"), (0.7, "TP"), (0.6, "FP"), (0.3, "FP")],
        min_labeled=5,
    )
    assert plenty.reliable is True
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_analysis.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'reefscanner.app.analysis'`.

- [ ] **Step 3: Implement**

Create `src/reefscanner/app/analysis.py`:

```python
"""What confidence threshold should this project use?

A scan run at confidence C emits every detection above C, and the reviewer
labels them. Raising the threshold afterwards is therefore perfectly
simulatable: the surviving events are known and so are their verdicts. No
rescan, no model, no guessing.

The one thing this can never see is what the detector missed *below* C. So the
numbers here describe recall relative to what this scan found, never absolute
recall — and the wording that says so is a correctness requirement, not copy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

#: Below this many scored, labeled events, a recommendation is a guess.
DEFAULT_MIN_LABELED = 5

_CONFIRMED = "TP"
_REJECTED = "FP"


@dataclass
class ThresholdPoint:
    """What would happen if the threshold were set here."""

    threshold: float
    kept: int
    confirmed_kept: int
    rejected_kept: int
    #: Confirmed animals that would fall below the line. The expensive error.
    confirmed_lost: int
    precision: float


@dataclass
class ThresholdAnalysis:
    labeled: int = 0
    confirmed: int = 0
    rejected: int = 0
    undecided: int = 0
    #: Labeled events with no confidence at all (scanned before detector mode).
    unscored: int = 0
    reliable: bool = False
    scan_threshold: Optional[float] = None
    recommended: Optional[float] = None
    recommendation: str = ""
    points: list[ThresholdPoint] = field(default_factory=list)


def analyse_thresholds(
    labeled: Sequence[tuple[Optional[float], str]],
    scan_threshold: Optional[float] = None,
    min_labeled: int = DEFAULT_MIN_LABELED,
) -> ThresholdAnalysis:
    """Sweep every threshold worth considering over labeled events.

    ``labeled`` is ``(ml_confidence, verdict)`` per reviewed event. Sweep points
    are the distinct observed confidences of events carrying evidence, because
    those are the only thresholds at which any count can change.
    """
    result = ThresholdAnalysis(labeled=len(labeled), scan_threshold=scan_threshold)

    scored = [(c, v) for c, v in labeled if c is not None]
    result.unscored = len(labeled) - len(scored)
    result.undecided = sum(1 for _, v in scored if v not in (_CONFIRMED, _REJECTED))

    # Only TP/FP carry evidence. 'unsure' is a human declining to call it, which
    # is not the same as either answer and must not tilt precision.
    evidence = [(c, v) for c, v in scored if v in (_CONFIRMED, _REJECTED)]
    result.confirmed = sum(1 for _, v in evidence if v == _CONFIRMED)
    result.rejected = len(evidence) - result.confirmed
    result.reliable = len(evidence) >= min_labeled

    if not evidence:
        result.recommendation = (
            "No labeled detections with a confidence score yet."
            if result.unscored
            else "Nothing labeled yet — review some events first."
        )
        return result

    for threshold in sorted({c for c, _ in evidence}):
        kept = [(c, v) for c, v in evidence if c >= threshold]
        confirmed_kept = sum(1 for _, v in kept if v == _CONFIRMED)
        result.points.append(
            ThresholdPoint(
                threshold=threshold,
                kept=len(kept),
                confirmed_kept=confirmed_kept,
                rejected_kept=len(kept) - confirmed_kept,
                confirmed_lost=result.confirmed - confirmed_kept,
                precision=(confirmed_kept / len(kept)) if kept else 0.0,
            )
        )

    if result.confirmed == 0:
        # Every threshold trivially loses nothing, so the rule would "recommend"
        # discarding every detection. Refuse to answer instead.
        result.recommendation = (
            "No confirmed animals yet — nothing to protect. "
            "Confirm at least one detection for a recommendation."
        )
        return result

    safe = [p for p in result.points if p.confirmed_lost == 0]
    best = max(safe, key=lambda p: p.threshold)
    result.recommended = best.threshold
    result.recommendation = (
        f"Highest threshold that keeps every confirmed animal. "
        f"At {best.threshold:.2f} you would review {best.kept} detection(s) "
        f"instead of {result.points[0].kept}, losing none."
    )
    return result
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_analysis.py -v`
Expected: PASS, 9 tests.

- [ ] **Step 5: Commit**

```bash
git add src/reefscanner/app/analysis.py tests/test_analysis.py
git commit -m "feat: threshold sweep over labeled events"
```

---

## Task 6: Threshold analysis endpoint

**Files:**
- Create: `src/reefscanner/app/routers/analysis.py`
- Modify: `src/reefscanner/app/main.py`
- Modify: `tests/test_app.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_app.py`:

```python
def test_threshold_analysis(client: TestClient, project_dirs) -> None:
    """Labels must turn into a confidence recommendation."""
    in_dir, out_dir = project_dirs
    project_id = client.post(
        "/api/projects",
        json={
            "name": "thresholds",
            "input_folder": str(in_dir),
            "output_folder": str(out_dir),
            "config": TEST_CONFIG,
        },
    ).json()["id"]
    job_id = client.post(f"/api/projects/{project_id}/jobs").json()["id"]
    _wait_for_job(client, job_id)

    events = client.get(f"/api/jobs/{job_id}/events").json()["items"]
    assert events, "need at least one event to analyse"
    client.put(f"/api/events/{events[0]['id']}/label", json={"verdict": "TP"})

    body = client.get(f"/api/jobs/{job_id}/threshold-analysis").json()
    assert body["confirmed"] == 1
    assert body["reliable"] is False, "one label is not evidence"
    assert body["scan_threshold"] == TEST_CONFIG["ml_confidence_threshold"]


def test_threshold_analysis_without_labels(client: TestClient, project_dirs) -> None:
    in_dir, out_dir = project_dirs
    project_id = client.post(
        "/api/projects",
        json={
            "name": "nolabels",
            "input_folder": str(in_dir),
            "output_folder": str(out_dir),
            "config": TEST_CONFIG,
        },
    ).json()["id"]
    job_id = client.post(f"/api/projects/{project_id}/jobs").json()["id"]
    _wait_for_job(client, job_id)

    body = client.get(f"/api/jobs/{job_id}/threshold-analysis").json()
    assert body["recommended"] is None
    assert body["points"] == []


def test_threshold_analysis_unknown_job(client: TestClient) -> None:
    assert client.get("/api/jobs/999/threshold-analysis").status_code == 404
```

Also add `"ml_confidence_threshold": 0.2` to the `TEST_CONFIG` dict at the top of
`tests/test_app.py`, so `scan_threshold` has a known value to assert against.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_app.py::test_threshold_analysis -v`
Expected: FAIL with 404 — the route does not exist.

- [ ] **Step 3: Implement the router**

Create `src/reefscanner/app/routers/analysis.py`:

```python
"""Turning review verdicts into a confidence recommendation."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from ..analysis import analyse_thresholds
from ..deps import get_session
from ..models import Event, Job, Label, Project

router = APIRouter(prefix="/api", tags=["analysis"])


@router.get("/jobs/{job_id}/threshold-analysis")
def threshold_analysis(
    job_id: int, session: Session = Depends(get_session)
) -> dict:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")

    rows = session.exec(
        select(Event.ml_confidence, Label.verdict)
        .join(Label, Label.event_id == Event.id)
        .where(Event.job_id == job_id)
    ).all()

    # The threshold the scan actually ran at bounds what can be simulated:
    # nothing below it was ever emitted, so nothing below it can be analysed.
    project = session.get(Project, job.project_id)
    scan_threshold = None
    if project is not None:
        from ..jobs import config_for

        scan_threshold = config_for(project).ml_confidence_threshold

    result = analyse_thresholds(
        [(c, v) for c, v in rows], scan_threshold=scan_threshold
    )
    return {
        "labeled": result.labeled,
        "confirmed": result.confirmed,
        "rejected": result.rejected,
        "undecided": result.undecided,
        "unscored": result.unscored,
        "reliable": result.reliable,
        "scan_threshold": result.scan_threshold,
        "recommended": result.recommended,
        "recommendation": result.recommendation,
        "points": [
            {
                "threshold": p.threshold,
                "kept": p.kept,
                "confirmed_kept": p.confirmed_kept,
                "rejected_kept": p.rejected_kept,
                "confirmed_lost": p.confirmed_lost,
                "precision": p.precision,
            }
            for p in result.points
        ],
    }
```

- [ ] **Step 4: Register it**

In `src/reefscanner/app/main.py`, add `analysis` to the routers import:

```python
from .routers import analysis, events, exports, jobs, media, projects, ws
```

and include it alongside the others:

```python
    app.include_router(analysis.router)
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/test_app.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/reefscanner/app/routers/analysis.py src/reefscanner/app/main.py tests/test_app.py
git commit -m "feat: threshold-analysis endpoint"
```

---

## Task 7: Nullable-column migration

Adding `Event.frame_path` to an existing database would otherwise mean deleting
real labels. This must land *before* the column does.

**Files:**
- Modify: `src/reefscanner/app/db.py`
- Create: `tests/test_migration.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_migration.py`:

```python
"""The startup migration that lets the schema grow without losing data."""

from __future__ import annotations

import sqlite3

from reefscanner.app.db import Database


def test_missing_nullable_column_is_added(tmp_path):
    """An older database gains the column and keeps every row."""
    path = tmp_path / "old.db"

    db = Database(path)
    db.create_all()
    db.dispose()

    # Simulate a database written before a column existed.
    conn = sqlite3.connect(path)
    conn.execute("ALTER TABLE event DROP COLUMN frame_path")
    conn.execute(
        "INSERT INTO job (project_id, status, progress, message, videos_total,"
        " videos_done, events_found) VALUES (1, 'done', 1.0, '', 1, 1, 1)"
    )
    conn.execute(
        "INSERT INTO event (job_id, event_id, source_video, start_seconds,"
        " end_seconds) VALUES (1, 'e1', '/x.mp4', 0.0, 1.0)"
    )
    conn.commit()
    conn.close()

    reopened = Database(path)
    reopened.create_all()

    columns = {
        row[1]
        for row in reopened.engine.raw_connection()
        .cursor()
        .execute("PRAGMA table_info(event)")
        .fetchall()
    }
    assert "frame_path" in columns

    rows = (
        reopened.engine.raw_connection()
        .cursor()
        .execute("SELECT event_id FROM event")
        .fetchall()
    )
    assert rows == [("e1",)], "existing rows must survive the migration"
    reopened.dispose()


def test_migration_is_idempotent(tmp_path):
    db = Database(tmp_path / "x.db")
    db.create_all()
    db.create_all()  # must not raise "duplicate column name"
    db.dispose()
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_migration.py -v`
Expected: FAIL — `frame_path` does not exist yet, so the `DROP COLUMN` errors.
This test is written against the end state and goes green once Task 8 adds the
column; run it again at the end of Task 8.

- [ ] **Step 3: Implement the migration**

In `src/reefscanner/app/db.py`, add to the `Database` class:

```python
    def create_all(self) -> None:
        """Create missing tables, then add any missing nullable columns.

        Not a migration framework. It handles exactly one kind of change --
        adding a nullable column -- because that is what a young schema mostly
        does, and the alternative is telling someone to delete a database full
        of hand-made labels. Drops, renames and type changes still need Alembic;
        this will not attempt them.
        """
        SQLModel.metadata.create_all(self.engine)
        self._add_missing_columns()

    def _add_missing_columns(self) -> None:
        from sqlalchemy import inspect, text

        inspector = inspect(self.engine)
        present_tables = set(inspector.get_table_names())

        for table in SQLModel.metadata.sorted_tables:
            if table.name not in present_tables:
                continue
            existing = {col["name"] for col in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing or not column.nullable:
                    continue
                type_sql = column.type.compile(self.engine.dialect)
                with self.engine.begin() as conn:
                    conn.execute(
                        text(
                            f'ALTER TABLE "{table.name}" '
                            f'ADD COLUMN "{column.name}" {type_sql}'
                        )
                    )
                logger.info("Added column %s.%s", table.name, column.name)
```

Add the logger at the top of `src/reefscanner/app/db.py`, below the imports:

```python
import logging

logger = logging.getLogger("reefscanner.app.db")
```

- [ ] **Step 4: Verify idempotency now**

Run: `uv run pytest tests/test_migration.py::test_migration_is_idempotent -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/reefscanner/app/db.py tests/test_migration.py
git commit -m "feat: add missing nullable columns on startup"
```

---

## Task 8: Write a clean training frame

**Files:**
- Modify: `src/reefscanner/engine/clips.py`
- Modify: `src/reefscanner/engine/config.py`
- Modify: `src/reefscanner/engine/pipeline.py`
- Modify: `src/reefscanner/app/models.py`, `jobs.py`, `exports.py`, `schemas.py`
- Modify: `src/reefscanner/app/routers/media.py`, `events.py`
- Modify: `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_pipeline.py`:

```python
def test_writes_clean_frame_beside_annotated_thumbnail(
    stub_detector, input_dir, output_dir
):
    """Training images must not have the detection box burned into them."""
    import cv2
    import numpy as np

    input_dir.mkdir()
    make_video(input_dir / "dive01.mp4", with_animal=True)
    cfg = _cfg(input_dir, output_dir)

    batch = process_folder(cfg, progress=False)
    assert batch.n_events >= 1
    event_id = batch.results[0].events[0].event_id

    thumb = output_dir / cfg.thumbnails_dirname / f"{event_id}{cfg.thumbnail_ext}"
    frame = output_dir / cfg.frames_dirname / f"{event_id}{cfg.thumbnail_ext}"
    assert thumb.exists(), "annotated thumbnail still needed for triage"
    assert frame.exists(), "clean frame needed for training"

    # The annotated one has the red box drawn on it; the clean one must not.
    # A pure-red pixel can only come from the rectangle we draw.
    def has_pure_red(path):
        img = cv2.imread(str(path))
        return bool(np.any((img[:, :, 2] > 200) & (img[:, :, 0] < 60) & (img[:, :, 1] < 60)))

    assert has_pure_red(thumb), "thumbnail should carry the drawn box"
    assert not has_pure_red(frame), "clean frame must have no annotation"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_pipeline.py::test_writes_clean_frame_beside_annotated_thumbnail -v`
Expected: FAIL — `AttributeError: 'ReefScannerConfig' object has no attribute 'frames_dirname'`.

- [ ] **Step 3: Add the config field**

In `src/reefscanner/engine/config.py`, beside `thumbnails_dirname`:

```python
    #: Clean peak frames, with no annotation drawn. These are the images the
    #: annotation exporters reference — a model trained on the annotated
    #: thumbnails would learn the red rectangle.
    frames_dirname: str = "frames"
```

- [ ] **Step 4: Split frame reading from frame writing**

In `src/reefscanner/engine/clips.py`, replace the body of `save_thumbnail` with a
read helper plus two writers:

```python
def read_peak_frame(event: Event, info: VideoInfo):
    """Decode the event's peak frame once. Callers may write it many ways."""
    cap = cv2.VideoCapture(str(info.path))
    try:
        if info.fps > 0:
            frame_idx = int(round(event.peak_timestamp * info.fps))
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ok, frame = cap.read()
        if not ok or frame is None:
            # Fallback: timestamp seek.
            cap.set(cv2.CAP_PROP_POS_MSEC, event.peak_timestamp * 1000.0)
            ok, frame = cap.read()
        if not ok or frame is None:
            raise RuntimeError(
                f"Could not read peak frame for event {event.event_id}"
            )
        return frame
    finally:
        cap.release()


def save_clean_frame(
    event: Event,
    info: VideoInfo,
    cfg: ReefScannerConfig,
    out_dir: Path,
    frame=None,
) -> Path:
    """Write the peak frame with nothing drawn on it — the training image."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{event.event_id}{cfg.thumbnail_ext}"
    if frame is None:
        frame = read_peak_frame(event, info)
    if not cv2.imwrite(str(path), frame):
        raise RuntimeError(f"Failed to write frame: {path}")
    return path


def save_thumbnail(
    event: Event,
    info: VideoInfo,
    cfg: ReefScannerConfig,
    out_dir: Path,
    draw_bbox: bool = True,
    frame=None,
) -> Path:
    """Save the peak frame with the detection box drawn, for human triage."""
    out_dir.mkdir(parents=True, exist_ok=True)
    thumb_path = out_dir / f"{event.event_id}{cfg.thumbnail_ext}"

    if frame is None:
        frame = read_peak_frame(event, info)
    # Copy before drawing: cv2.rectangle mutates in place, and the caller is
    # very likely holding this same array to write the clean frame.
    frame = frame.copy()

    if draw_bbox and event.peak_bbox:
        x, y, w, h = event.peak_bbox
        cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 0, 255), 2)

    if not cv2.imwrite(str(thumb_path), frame):
        raise RuntimeError(f"Failed to write thumbnail: {thumb_path}")
    return thumb_path
```

- [ ] **Step 5: Write both from the pipeline**

In `src/reefscanner/engine/pipeline.py`, change the import:

```python
from .clips import extract_clip, read_peak_frame, resolve_ffmpeg, save_clean_frame, save_thumbnail
```

In `process_video`, add the frames directory beside the others:

```python
    frames_dir = out_dir / cfg.frames_dirname
```

and replace the per-event loop body:

```python
    rows: list[dict] = []
    for event in events:
        clip_path = extract_clip(event, info, cfg, clips_dir, ffmpeg=ffmpeg)
        # One decode, two writes: the annotated thumbnail for triage and the
        # clean frame for training exports.
        peak = read_peak_frame(event, info)
        thumb_path = save_thumbnail(event, info, cfg, thumbs_dir, frame=peak)
        save_clean_frame(event, info, cfg, frames_dir, frame=peak)
        rows.append(event_to_row(event, info, str(clip_path), str(thumb_path)))
    return events, rows
```

- [ ] **Step 6: Run to verify it passes**

Run: `uv run pytest tests/test_pipeline.py::test_writes_clean_frame_beside_annotated_thumbnail -v`
Expected: PASS.

- [ ] **Step 7: Record the frame path in the database**

In `src/reefscanner/app/models.py`, beside `thumbnail_path` on `Event`:

```python
    #: Clean peak frame with no annotation — what the exporters reference.
    #: Null for events scanned before clean frames existed.
    frame_path: Optional[str] = None
```

In `src/reefscanner/app/jobs.py`, inside `_record_events`, extend the path block:

```python
                clip = thumb = frame = None
                if out_dir is not None:
                    suffix = Path(result.video).suffix or ".mp4"
                    clip = str(out_dir / cfg.clips_dirname / f"{ev.event_id}{suffix}")
                    thumb = str(
                        out_dir / cfg.thumbnails_dirname
                        / f"{ev.event_id}{cfg.thumbnail_ext}"
                    )
                    frame = str(
                        out_dir / cfg.frames_dirname
                        / f"{ev.event_id}{cfg.thumbnail_ext}"
                    )
```

and add `frame_path=frame,` to the `Event(...)` constructor call beside
`thumbnail_path=thumb,`.

- [ ] **Step 8: Serve and export the clean frame**

In `src/reefscanner/app/routers/media.py`, change `_resolve` to handle three kinds:

```python
    raw = {
        "clip": event.clip_path,
        "thumbnail": event.thumbnail_path,
        "frame": event.frame_path,
    }.get(kind)
```

and add the route:

```python
@router.get("/frame/{event_id}")
def get_frame(event_id: int, session: Session = Depends(get_session)) -> FileResponse:
    path = _resolve(session, event_id, "frame")
    return FileResponse(path, filename=path.name)
```

In `src/reefscanner/app/exports.py`, make the exporters prefer the clean frame.
Replace the `_frame_size` preamble and the COCO `file_name` with a shared helper:

```python
def _image_path(event: Event) -> Optional[str]:
    """The image an annotation should point at.

    The clean frame when we have one; the thumbnail otherwise, for events
    scanned before clean frames existed. The thumbnail has the detection box
    drawn on it, which is why it is the fallback and not the choice.
    """
    return event.frame_path or event.thumbnail_path
```

Then in `_frame_size`, replace `event.thumbnail_path` with `_image_path(event)`
(both the truthiness check and the `cv2.imread` argument), and in `export_coco`
replace `Path(event.thumbnail_path or "").name` with `Path(_image_path(event) or "").name`.

- [ ] **Step 9: Expose it in the API schema**

In `src/reefscanner/app/schemas.py`, add to `EventRead` beside `thumbnail_url`:

```python
    frame_url: Optional[str] = None
```

In `src/reefscanner/app/routers/events.py`, inside `_event_read`, add:

```python
        frame_url=f"/api/media/frame/{event.id}" if event.frame_path else None,
```

- [ ] **Step 10: Run the full suite**

Run: `uv run pytest -v`
Expected: PASS, including `tests/test_migration.py` now that `frame_path` exists.

- [ ] **Step 11: Commit**

```bash
git add -A
git commit -m "feat: export a clean training frame beside the annotated thumbnail

The annotation exporters referenced the thumbnail, which has the detection box
drawn onto it in red -- a model trained on those would learn the annotation.
The peak frame is now decoded once and written twice."
```

---

## Task 9: Frontend — threshold panel and settings

**Files:**
- Create: `frontend/src/components/ThresholdPanel.tsx`
- Modify: `frontend/src/lib/types.ts`, `api.ts`, `queries.ts`
- Modify: `frontend/src/pages/JobDetail.tsx`, `ProjectDetail.tsx`

- [ ] **Step 1: Add the types**

Append to `frontend/src/lib/types.ts`:

```typescript
export interface ThresholdPoint {
  threshold: number;
  kept: number;
  confirmed_kept: number;
  rejected_kept: number;
  confirmed_lost: number;
  precision: number;
}

export interface ThresholdAnalysis {
  labeled: number;
  confirmed: number;
  rejected: number;
  undecided: number;
  unscored: number;
  reliable: boolean;
  scan_threshold: number | null;
  recommended: number | null;
  recommendation: string;
  points: ThresholdPoint[];
}
```

Add `frame_url: string | null;` to the `ReefEvent` interface, beside `thumbnail_url`.

- [ ] **Step 2: Add the API call and hook**

In `frontend/src/lib/api.ts`, add to the `api` object:

```typescript
  thresholdAnalysis: (jobId: number) =>
    request<ThresholdAnalysis>(`/api/jobs/${jobId}/threshold-analysis`),
```

and add `ThresholdAnalysis` to the type import at the top of the file.

In `frontend/src/lib/queries.ts`, add the key and hook:

```typescript
export const thresholdKey = (jobId: number) => ["thresholds", jobId] as const;

export const useThresholdAnalysis = (jobId: number) =>
  useQuery({
    queryKey: thresholdKey(jobId),
    queryFn: () => api.thresholdAnalysis(jobId),
  });
```

In `useSaveLabel`'s `onSuccess`, invalidate it too, so the recommendation moves
as verdicts are recorded:

```typescript
      qc.invalidateQueries({ queryKey: thresholdKey(jobId) });
```

- [ ] **Step 3: Build the panel**

Create `frontend/src/components/ThresholdPanel.tsx`:

```tsx
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { keys, useProject, useThresholdAnalysis } from "../lib/queries";
import { Button, ErrorNote, cx } from "./ui";

/**
 * What confidence should this project use?
 *
 * Every number here is simulated from events that were actually emitted and
 * labeled, so it says nothing about what the detector missed below the scan
 * threshold. The wording reflects that — "of what this scan found" is not
 * hedging, it is the honest scope of the claim.
 */
export function ThresholdPanel({
  jobId,
  projectId,
}: {
  jobId: number;
  projectId: number;
}) {
  const { data, isLoading } = useThresholdAnalysis(jobId);
  const { data: project } = useProject(projectId);
  const queryClient = useQueryClient();

  const apply = useMutation({
    // PATCH replaces the whole config blob rather than merging into it, so the
    // existing settings must be sent back or applying a threshold would wipe
    // every other tunable on the project.
    mutationFn: (threshold: number) =>
      api.updateProject(projectId, {
        config: { ...(project?.config ?? {}), ml_confidence_threshold: threshold },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: keys.project(projectId) });
    },
  });

  if (isLoading || !data) return null;
  if (data.labeled === 0) {
    return (
      <div className="panel px-4 py-3 text-sm text-faint">
        Review a few events and this will tell you what confidence threshold to
        use — measured on your footage, not a benchmark.
      </div>
    );
  }

  return (
    <section className="panel p-4">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="text-sm font-medium">Confidence threshold</h2>
        <span className="legend">
          from {data.confirmed} confirmed · {data.rejected} rejected
          {data.undecided > 0 && ` · ${data.undecided} undecided`}
          {data.unscored > 0 && ` · ${data.unscored} unscored`}
        </span>
      </div>

      <div className="flex flex-wrap items-center gap-4">
        {data.recommended !== null ? (
          <>
            <div>
              <div className="legend">Recommended</div>
              <div className="tabular text-2xl leading-tight text-signal">
                {data.recommended.toFixed(2)}
              </div>
            </div>
            <p className="min-w-[14rem] flex-1 text-xs text-dim">
              {data.recommendation}
            </p>
            <Button
              variant="primary"
              size="sm"
              onClick={() => apply.mutate(data.recommended as number)}
              disabled={apply.isPending || !project}
            >
              {apply.isSuccess ? "Applied" : "Apply to project"}
            </Button>
          </>
        ) : (
          <p className="text-xs text-dim">{data.recommendation}</p>
        )}
      </div>

      <ErrorNote error={apply.error} />

      {!data.reliable && data.points.length > 0 && (
        <p className="mt-3 rounded-[3px] border border-hedge/40 bg-hedge/10 px-2.5 py-1.5 text-xs text-hedge">
          Only {data.confirmed + data.rejected} labeled detection(s) — treat this
          as a hint, not a measurement. Review more to firm it up.
        </p>
      )}

      {data.points.length > 0 && (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[34rem] text-left">
            <thead>
              <tr className="legend">
                <th className="py-1 pr-4 font-normal">Threshold</th>
                <th className="py-1 pr-4 font-normal">To review</th>
                <th className="py-1 pr-4 font-normal">Real</th>
                <th className="py-1 pr-4 font-normal">Junk</th>
                <th className="py-1 pr-4 font-normal">Animals lost</th>
                <th className="py-1 font-normal">Precision</th>
              </tr>
            </thead>
            <tbody className="tabular text-sm">
              {data.points.map((point) => {
                const isPick = point.threshold === data.recommended;
                return (
                  <tr
                    key={point.threshold}
                    className={cx(
                      "border-t border-rule",
                      isPick && "bg-signal/10 text-signal",
                    )}
                  >
                    <td className="py-1.5 pr-4">{point.threshold.toFixed(2)}</td>
                    <td className="py-1.5 pr-4">{point.kept}</td>
                    <td className="py-1.5 pr-4">{point.confirmed_kept}</td>
                    <td className="py-1.5 pr-4 text-faint">{point.rejected_kept}</td>
                    <td
                      className={cx(
                        "py-1.5 pr-4",
                        point.confirmed_lost > 0 && !isPick && "text-reject",
                      )}
                    >
                      {point.confirmed_lost}
                    </td>
                    <td className="py-1.5">
                      {(point.precision * 100).toFixed(0)}%
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="mt-2 text-xs text-faint">
            Simulated from detections this scan emitted at confidence{" "}
            {data.scan_threshold?.toFixed(2) ?? "—"}. It cannot show animals the
            detector missed below that line.
          </p>
        </div>
      )}
    </section>
  );
}
```

- [ ] **Step 4: Put it on the run page**

In `frontend/src/pages/JobDetail.tsx`, import it:

```tsx
import { ThresholdPanel } from "../components/ThresholdPanel";
```

and render it directly after the review-progress panel block (the one that opens
with `{page && page.total > 0 && (`), before the filters:

```tsx
      {job && <ThresholdPanel jobId={id} projectId={job.project_id} />}
```

- [ ] **Step 5: Promote confidence and hide motion knobs**

In `frontend/src/pages/ProjectDetail.tsx`, add to the `PRIMARY` array, directly
after the `detector` entry:

```typescript
  {
    key: "ml_confidence_threshold",
    label: "Confidence threshold",
    hint: "Detections below this are discarded. Review some events and the run page will recommend a value.",
  },
```

Then remove the `min_blob_area` entry from `PRIMARY` — it is a motion pre-filter
control now, not a primary one, and belongs under "all settings".

Add the motion-field list and filter above the component:

```typescript
/** Motion-gate controls. Only meaningful when the pre-filter is switched on. */
const MOTION_ONLY_KEYS = new Set([
  "min_blob_area",
  "persistence_frames",
  "bg_subtractor",
  "detect_shadows",
  "bg_history",
  "mog2_var_threshold",
  "morph_kernel_size",
  "warmup_frames",
]);
```

and in the component, filter the "all settings" list so motion knobs only show
when the pre-filter is on. Replace the `otherKeys` definition with:

```typescript
  const prefilterOn = Boolean(values["motion_prefilter"]);
  const otherKeys = Object.keys(effective)
    .filter((k) => !PRIMARY.some((f) => f.key === k))
    .filter((k) => prefilterOn || !MOTION_ONLY_KEYS.has(k))
    .sort();
```

- [ ] **Step 6: Make the min-confidence slider show its cost**

The spec calls for the slider to say what a threshold would keep and lose. It
reads from the same analysis, so this is display only.

In `frontend/src/pages/JobDetail.tsx`, import the hook:

```tsx
import { useThresholdAnalysis } from "../lib/queries";
```

Inside the component, alongside the other queries:

```tsx
  const { data: thresholds } = useThresholdAnalysis(id);
```

Then replace the closing `</label>` of the min-confidence control with a readout
of the nearest sweep point at or below the slider position:

```tsx
          <span className="tabular w-8 text-xs text-dim">
            {(filters.min_confidence ?? 0).toFixed(2)}
          </span>
          {(() => {
            const at = filters.min_confidence ?? 0;
            // The last sweep point at or below the slider describes what this
            // position would do; below every point, nothing is filtered out.
            const point = [...(thresholds?.points ?? [])]
              .reverse()
              .find((p) => p.threshold <= at);
            if (!point || at === 0) return null;
            return (
              <span className="legend">
                keeps {point.kept} ·{" "}
                <span className={point.confirmed_lost > 0 ? "text-reject" : ""}>
                  loses {point.confirmed_lost} confirmed
                </span>
              </span>
            );
          })()}
        </label>
```

- [ ] **Step 7: Typecheck and build**

Run: `cd frontend && npx tsc --noEmit -p tsconfig.app.json && npm run build`
Expected: no type errors, build succeeds.

- [ ] **Step 8: Verify against a real server**

Run the app, open a run with labeled events, and confirm the panel shows a
recommendation and that **Apply** changes the project's confidence setting.

```bash
uv run reefscanner serve --port 8801
```

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat: threshold recommendation panel and settings cleanup"
```

---

## Task 10: Documentation

**Files:**
- Modify: `README.md`, `SPEC.md`, `PLAN.md`

- [ ] **Step 1: Update the README detector section**

Replace the three detector-mode paragraphs under "How it works" with:

```markdown
**`marine` (default) — SharkTrack.** A YOLOv8 model trained on real BRUVS
footage, single `elasmobranch` class (sharks *and* rays — it does not tell them
apart), MIT-licensed. Weights download automatically on first use (~6 MB, cached
in `~/.cache/reefscanner`).

**`generic`** runs a stock COCO YOLO as a crude objectness proposer. Useful for
experimenting, not for surveys.

Motion-only triage was removed in v2. It could not tell a small fish close to the
camera from a large animal far away — monocular video has no depth cue, so a blob
size filter is guessing at distance. The motion gate survives as an optional
pre-filter that skips dead-static frames.
```

- [ ] **Step 2: Add a Thresholds section to the README**

After the "Reviewing" section, add:

```markdown
## Choosing a confidence threshold

Once you have labeled some events, the run page recommends a threshold measured
on *your* footage: the highest value that keeps every animal you confirmed.
Below it you review junk for nothing; above it you start missing real sightings.

The sweep is simulated from detections the scan actually emitted, so it tells you
nothing about animals the detector missed below the threshold you scanned at.
It reports recall relative to what that scan found.
```

- [ ] **Step 3: Record the decision in SPEC.md**

Append to the §11.1 table in `SPEC.md`:

```
| Motion gate is the recall source | Detector is; motion is an optional pre-filter | Tested on real BRUV footage: motion cannot separate a small fish nearby from a large animal far away. Monocular video has no depth cue, so `min_blob_area` is a proxy for distance the data does not support. |
```

- [ ] **Step 4: Update PLAN.md**

Add to the "Open items" section:

```markdown
- **Motion-based tracking** is the next natural use of `MotionGate`: once the
  detector has found an animal, link it across frames. Kept for that reason.
- **Fine-tuning** is now unblocked — clean frames are exported — but needs far
  more labeled data than a few dives provide.
```

- [ ] **Step 5: Commit**

```bash
git add README.md SPEC.md PLAN.md
git commit -m "docs: detector-first, and how to read the threshold recommendation"
```
