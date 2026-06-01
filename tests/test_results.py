"""CSV writer + schema migration (results.py)."""

import csv

import pandas as pd

from reefscanner.results import (
    CSV_COLUMNS,
    LEGACY_CSV_COLUMNS,
    CsvWriter,
)


def _write_raw(path, header, rows):
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def test_fresh_file_gets_current_header(tmp_path):
    csv_path = tmp_path / "results.csv"
    CsvWriter(csv_path)
    with open(csv_path, newline="") as fh:
        assert next(csv.reader(fh)) == CSV_COLUMNS


def test_legacy_csv_is_migrated_in_place(tmp_path):
    # A v1 (pre-detected_class) file: 13-column header + 13-column rows.
    csv_path = tmp_path / "results.csv"
    legacy_row = ["clipA-0", "/v/a.mp4", "1.0", "3.0", "2.0", "", "120.0", "",
                  "/clips/a.mp4", "/thumbs/a.jpg", "", "", ""]
    assert len(legacy_row) == len(LEGACY_CSV_COLUMNS)
    _write_raw(csv_path, LEGACY_CSV_COLUMNS, [legacy_row])

    CsvWriter(csv_path)  # opening triggers migration

    df = pd.read_csv(csv_path)  # the operation that used to raise ParserError
    assert list(df.columns) == CSV_COLUMNS
    assert df.iloc[0]["event_id"] == "clipA-0"
    assert df.iloc[0]["clip_path"] == "/clips/a.mp4"  # not shifted
    assert pd.isna(df.iloc[0]["detected_class"])       # new column left blank
    # Original preserved as a backup.
    assert (tmp_path / "results.csv.pre-migration.bak").exists()


def test_mixed_width_csv_migrates_losslessly(tmp_path):
    # Real-world breakage: a legacy 13-col header with one legacy row and one
    # 14-col row a newer version already appended.
    csv_path = tmp_path / "results.csv"
    legacy_row = ["old-0", "/v/a.mp4", "1.0", "3.0", "2.0", "", "120.0", "",
                  "/clips/a.mp4", "/thumbs/a.jpg", "", "", ""]
    new_row = ["new-0", "/v/b.mp4", "1.0", "3.0", "2.0", "", "", "0.42",
               "elasmobranch", "/clips/b.mp4", "/thumbs/b.jpg", "", "", ""]
    assert len(new_row) == len(CSV_COLUMNS)
    _write_raw(csv_path, LEGACY_CSV_COLUMNS, [legacy_row, new_row])

    CsvWriter(csv_path)

    df = pd.read_csv(csv_path)
    assert list(df.columns) == CSV_COLUMNS
    assert set(df["event_id"]) == {"old-0", "new-0"}
    new = df[df["event_id"] == "new-0"].iloc[0]
    assert new["detected_class"] == "elasmobranch"  # 14-col row kept aligned
    assert new["clip_path"] == "/clips/b.mp4"
    assert new["ml_confidence"] == 0.42


def test_append_after_migration_is_consistent(tmp_path):
    csv_path = tmp_path / "results.csv"
    legacy_row = ["old-0", "/v/a.mp4", "1.0", "3.0", "2.0", "", "120.0", "",
                  "/clips/a.mp4", "/thumbs/a.jpg", "", "", ""]
    _write_raw(csv_path, LEGACY_CSV_COLUMNS, [legacy_row])

    w = CsvWriter(csv_path)
    w.append_rows([{c: "" for c in CSV_COLUMNS} | {"event_id": "new-1"}])

    df = pd.read_csv(csv_path)
    assert list(df.columns) == CSV_COLUMNS
    assert set(df["event_id"]) == {"old-0", "new-1"}
    assert w.existing_event_ids() == {"old-0", "new-1"}
