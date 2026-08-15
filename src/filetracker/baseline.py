"""Manifest persistence with atomic writes and undo snapshots.

The manifest is a JSON document mapping relative file paths to their
:class:`FileState`-equivalent entry (including the stored text content, which
is required to lazily reconstruct old content and unified diffs).

Atomicity is guaranteed by writing to a ``*.tmp`` file first, flushing and
fsync-ing it, then performing a single atomic ``os.replace`` onto the final
path. A crash before the replace leaves the previous manifest untouched.
"""

from __future__ import annotations

import json
import os
import tempfile

MANIFEST_FILENAME = "manifest.json"
SNAPSHOT_DIRNAME = "snapshots"
SNAPSHOT_INDEX = "index.json"


class BaselineManager:
    def __init__(self, baseline_dir: str):
        self.baseline_dir = os.path.abspath(baseline_dir)
        self.manifest_path = os.path.join(self.baseline_dir, MANIFEST_FILENAME)
        self.snapshots_dir = os.path.join(self.baseline_dir, SNAPSHOT_DIRNAME)
        self._snap_index_path = os.path.join(self.snapshots_dir, SNAPSHOT_INDEX)
        os.makedirs(self.baseline_dir, exist_ok=True)
        os.makedirs(self.snapshots_dir, exist_ok=True)

    # ---- manifest I/O -------------------------------------------------

    def load(self) -> dict:
        """Return the current manifest, or an empty manifest if none exists."""
        if not os.path.exists(self.manifest_path):
            return {"version": 1, "files": {}}
        try:
            with open(self.manifest_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError):
            return {"version": 1, "files": {}}
        data.setdefault("version", 1)
        data.setdefault("files", {})
        return data

    def save(self, manifest: dict) -> None:
        """Atomically write *manifest* to disk.

        Raises on failure *before* the final replace, so the on-disk manifest
        is never left in a half-written state.
        """
        os.makedirs(self.baseline_dir, exist_ok=True)
        # Write to a temp file in the same directory (same filesystem -> atomic move).
        fd, tmp_name = tempfile.mkstemp(
            dir=self.baseline_dir, suffix=".tmp", prefix=".manifest-"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(manifest, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, self.manifest_path)
        finally:
            if os.path.exists(tmp_name):
                try:
                    os.remove(tmp_name)
                except OSError:
                    pass

    # ---- content access ------------------------------------------------

    def get_content(self, manifest: dict, path: str) -> str | None:
        entry = manifest["files"].get(path)
        if entry is None:
            return None
        return entry.get("content")

    # ---- undo snapshots ------------------------------------------------

    def _read_index(self) -> list[str]:
        if not os.path.exists(self._snap_index_path):
            return []
        try:
            with open(self._snap_index_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError):
            return []
        return list(data.get("stack", []))

    def _write_index(self, stack: list[str]) -> None:
        with open(self._snap_index_path, "w", encoding="utf-8") as fh:
            json.dump({"stack": stack}, fh)

    def push_snapshot(self, manifest: dict) -> None:
        """Persist a copy of *manifest* onto the undo stack."""
        stack = self._read_index()
        snap_name = f"snapshot-{len(stack):04d}.json"
        snap_path = os.path.join(self.snapshots_dir, snap_name)
        with open(snap_path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, ensure_ascii=False, indent=2)
        stack.append(snap_name)
        self._write_index(stack)

    def pop_snapshot(self) -> dict | None:
        """Pop and return the most recent snapshot, or None if empty."""
        stack = self._read_index()
        if not stack:
            return None
        snap_name = stack.pop()
        self._write_index(stack)
        snap_path = os.path.join(self.snapshots_dir, snap_name)
        try:
            with open(snap_path, "r", encoding="utf-8") as fh:
                manifest = json.load(fh)
        except (json.JSONDecodeError, OSError):
            return None
        finally:
            try:
                os.remove(snap_path)
            except OSError:
                pass
        return manifest
