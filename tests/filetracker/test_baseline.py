"""Tests for atomic manifest persistence and undo snapshots."""

from __future__ import annotations

import os

import pytest

from filetracker.baseline import BaselineManager


def _make_manifest(content: str) -> dict:
    return {
        "version": 1,
        "files": {
            "a.py": {
                "path": "a.py",
                "exists": True,
                "size": len(content),
                "mtime": 1.0,
                "sha256": "x",
                "content": content,
            }
        },
    }


def test_atomic_manifest_update(tmp_path, monkeypatch):
    bm = BaselineManager(str(tmp_path))
    bm.save(_make_manifest("old"))

    # Simulate a crash right at the atomic replace step.
    def boom(src, dst):
        raise OSError("simulated crash during replace")

    monkeypatch.setattr(os, "replace", boom)

    with pytest.raises(OSError):
        bm.save(_make_manifest("new"))

    # On-disk manifest must be untouched (still the old, valid content).
    data = bm.load()
    assert data["files"]["a.py"]["content"] == "old"


def test_load_missing_manifest_returns_empty(tmp_path):
    bm = BaselineManager(str(tmp_path))
    assert bm.load() == {"version": 1, "files": {}}


def test_snapshot_push_pop_roundtrip(tmp_path):
    bm = BaselineManager(str(tmp_path))
    bm.push_snapshot(_make_manifest("v1"))
    bm.push_snapshot(_make_manifest("v2"))
    popped = bm.pop_snapshot()
    assert popped["files"]["a.py"]["content"] == "v2"
    popped = bm.pop_snapshot()
    assert popped["files"]["a.py"]["content"] == "v1"
    assert bm.pop_snapshot() is None
