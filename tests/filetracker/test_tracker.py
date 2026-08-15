"""Tests for the FileTracker transaction lifecycle: scan/commit/undo/rollback."""

from __future__ import annotations

import pytest

from filetracker.models import ChangeStatus
from filetracker.tracker import FileTracker


def _write(root, name, text):
    p = root / name
    p.write_bytes(text.encode("utf-8"))
    return p


def test_initial_scan_reports_added(tmp_path):
    _write(tmp_path, "a.py", "x")
    tracker = FileTracker(root=str(tmp_path))
    cs = tracker.scan()
    assert cs.total == 1
    assert cs.added[0].path == "a.py"
    assert cs.added[0].status == ChangeStatus.ADDED


def test_scan_after_commit_is_clean(tmp_path):
    _write(tmp_path, "a.py", "x")
    tracker = FileTracker(root=str(tmp_path))
    tracker.scan()
    tracker.commit()
    cs = tracker.scan()
    assert cs.has_changes is False


def test_modified_detection(tmp_path):
    _write(tmp_path, "a.py", "x")
    tracker = FileTracker(root=str(tmp_path))
    tracker.scan()
    tracker.commit()

    _write(tmp_path, "a.py", "xy")
    cs = tracker.scan()
    assert len(cs.modified) == 1
    assert cs.modified[0].status == ChangeStatus.MODIFIED


def test_deleted_detection(tmp_path):
    _write(tmp_path, "a.py", "x")
    tracker = FileTracker(root=str(tmp_path))
    tracker.scan()
    tracker.commit()

    (tmp_path / "a.py").unlink()
    cs = tracker.scan()
    assert len(cs.deleted) == 1
    assert cs.deleted[0].status == ChangeStatus.DELETED


def test_failed_commit_rollback(tmp_path, monkeypatch):
    _write(tmp_path, "a.py", "x")
    tracker = FileTracker(root=str(tmp_path))
    tracker.scan()
    tracker.commit()

    # Force the atomic write to fail.
    def boom(manifest):
        raise RuntimeError("disk write failed")

    monkeypatch.setattr(tracker.baseline, "save", boom)

    with pytest.raises(RuntimeError):
        tracker.commit()

    # Baseline must be unchanged: a.py still tracked with original content.
    cs = tracker.scan()
    assert cs.has_changes is False
    assert tracker.read_baseline_content("a.py") == "x"


def test_undo_snapshot(tmp_path):
    _write(tmp_path, "a.py", "v1")
    tracker = FileTracker(root=str(tmp_path))
    tracker.scan()
    tracker.commit()

    _write(tmp_path, "a.py", "v2")
    tracker.scan()
    tracker.commit()

    # Undo once -> baseline back to v1, working dir untouched (still v2).
    assert tracker.undo() is True
    cs = tracker.scan()
    assert len(cs.modified) == 1
    assert tracker.read_baseline_content("a.py") == "v1"
    assert (tmp_path / "a.py").read_text() == "v2"

    # Undo again -> baseline back to empty.
    assert tracker.undo() is True
    cs2 = tracker.scan()
    assert len(cs2.added) == 1
    assert (tmp_path / "a.py").read_text() == "v2"

    # Nothing left to undo.
    assert tracker.undo() is False


def test_filechange_diff_and_content(tmp_path):
    _write(tmp_path, "a.py", "line1\nline2\n")
    tracker = FileTracker(root=str(tmp_path))
    tracker.scan()
    tracker.commit()

    _write(tmp_path, "a.py", "line1\nline2-changed\n")
    cs = tracker.scan()
    change = cs.modified[0]
    assert change.old_content() == "line1\nline2\n"
    assert change.new_content() == "line1\nline2-changed\n"
    diff = change.diff()
    assert "-line2" in diff
    assert "+line2-changed" in diff


def test_commit_stores_message_metadata(tmp_path):
    _write(tmp_path, "a.py", "x")
    tracker = FileTracker(root=str(tmp_path))
    tracker.scan()
    tracker.commit(message="initial import")
    manifest = tracker.baseline.load()
    assert manifest["message"] == "initial import"
    assert "committed_at" in manifest
