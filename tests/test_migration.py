"""The startup migration that lets the schema grow without losing data."""

from __future__ import annotations

import sqlite3

from reefscanner.app.db import Database


def _columns(path, table: str) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    finally:
        conn.close()


def test_missing_nullable_column_is_added(tmp_path):
    """An older database gains the column and keeps every row.

    Simulated by dropping a nullable column the current model has, which is
    exactly the shape of a database written before that column was added.
    """
    path = tmp_path / "old.db"
    db = Database(path)
    db.create_all()
    db.dispose()

    conn = sqlite3.connect(path)
    conn.execute("ALTER TABLE event DROP COLUMN frame_width")
    conn.execute(
        "INSERT INTO job (project_id, status, progress, message, videos_total,"
        " videos_done, events_found) VALUES (1, 'done', 1.0, '', 1, 1, 1)"
    )
    conn.execute(
        "INSERT INTO event (job_id, event_id, source_video, start_seconds,"
        " end_seconds, duration_seconds, peak_timestamp, peak_score,"
        " start_timestamp) VALUES (1, 'e1', '/x.mp4', 0.0, 1.0, 1.0, 0.5, 0.9, '')"
    )
    conn.commit()
    conn.close()
    assert "frame_width" not in _columns(path, "event")

    reopened = Database(path)
    reopened.create_all()
    reopened.dispose()

    assert "frame_width" in _columns(path, "event")
    conn = sqlite3.connect(path)
    rows = conn.execute("SELECT event_id, frame_width FROM event").fetchall()
    conn.close()
    assert rows == [("e1", None)], "existing rows must survive, new column null"


def test_migration_is_idempotent(tmp_path):
    db = Database(tmp_path / "x.db")
    db.create_all()
    db.create_all()  # must not raise "duplicate column name"
    db.dispose()
