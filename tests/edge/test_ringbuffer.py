"""The encoded ring buffer: keeps the pre-roll, honours holds, cuts clips."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from reefscanner.core.clips import resolve_ffmpeg
from reefscanner.core.config import ReefScannerConfig
from reefscanner.core.videoio import probe_video
from reefscanner.edge.ringbuffer import RingBuffer

FPS = 10


@pytest.fixture
def buffer(tmp_path: Path):
    buf = RingBuffer(
        tmp_path / "buf", fps=FPS, width=64, height=48,
        ffmpeg=resolve_ffmpeg(ReefScannerConfig()), keep_seconds=4.0, segment_seconds=1.0,
    )
    buf.start()
    yield buf
    buf.close()


def _feed(buf: RingBuffer, seconds: float) -> None:
    for i in range(int(seconds * FPS)):
        buf.write(np.full((48, 64, 3), i % 250, np.uint8))


def _segments(buf: RingBuffer) -> list[int]:
    return sorted(int(p.stem.split("_")[1]) for p in buf.folder.glob("seg_*.ts"))


def test_old_footage_is_deleted_beyond_the_pre_roll(buffer: RingBuffer) -> None:
    _feed(buffer, 20)
    kept = _segments(buffer)
    # Pre-roll 4 s plus one segment of slack, plus the one being written.
    assert kept[0] >= 20 - 4 - 1 - 1
    assert len(kept) <= 7


def test_a_hold_keeps_footage_until_released(buffer: RingBuffer) -> None:
    _feed(buffer, 3)
    key = buffer.hold(1.0)
    _feed(buffer, 15)
    assert _segments(buffer)[0] == 1
    buffer.release(key)
    _feed(buffer, 2)
    assert _segments(buffer)[0] > 1


def test_a_clip_covers_the_requested_span_in_whole_segments(buffer: RingBuffer, tmp_path: Path) -> None:
    _feed(buffer, 10)
    assert buffer.wait_until(7.0, timeout=10)
    clip = tmp_path / "clip.mp4"
    start = buffer.cut(5.5, 7.2, clip)
    assert start == 5.0
    info = probe_video(clip)
    assert info.duration_seconds == pytest.approx(3.0, abs=0.15)  # segments 5, 6, 7


def test_finishing_makes_the_last_partial_segment_cuttable(buffer: RingBuffer, tmp_path: Path) -> None:
    _feed(buffer, 2.5)
    buffer.finish()
    assert buffer.complete_until() == pytest.approx(2.5)
    buffer.cut(0.0, 2.5, tmp_path / "tail.mp4")
    assert probe_video(tmp_path / "tail.mp4").duration_seconds == pytest.approx(2.5, abs=0.15)
