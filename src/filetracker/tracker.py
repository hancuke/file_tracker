"""FileTracker: the main API for physical file-level change tracking."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from filetracker.baseline import BaselineManager
from filetracker.diff import is_binary
from filetracker.models import ChangeSet, ChangeStatus, FileChange, FileState
from filetracker.scanner import FileScanner

DEFAULT_BASELINE_SUBDIR = os.path.join(".filetracker", "baseline")


def _read_text(abs_path: str) -> str | None:
    """Read a file as UTF-8 text; return None for binary/undecodable files."""
    try:
        with open(abs_path, "rb") as fh:
            data = fh.read()
    except OSError:
        return None
    if is_binary(data):
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _entry_to_state(entry: dict) -> FileState:
    return FileState(
        path=entry.get("path", ""),
        exists=entry.get("exists", True),
        size=entry.get("size"),
        mtime=entry.get("mtime"),
        sha256=entry.get("sha256"),
    )


class FileTracker:
    """Track physical file changes relative to a committed baseline.

    Typical workflow::

        tracker = FileTracker(root="./src")
        changes = tracker.scan()          # read-only
        if changes.has_changes:
            ... process ...
            tracker.commit("advanced")    # advance baseline
    """

    def __init__(
        self,
        root: str,
        exclude: list[str] | None = None,
        baseline_dir: str | None = None,
    ):
        self.root = os.path.abspath(root)
        self.exclude = list(exclude or [])
        if baseline_dir is None:
            baseline_dir = os.path.join(self.root, DEFAULT_BASELINE_SUBDIR)
        self.baseline = BaselineManager(baseline_dir)
        self.scanner = FileScanner(
            self.root, exclude=self.exclude, baseline_dir=self.baseline.baseline_dir
        )
        self._baseline_cache: dict | None = None

    # ---- public API ---------------------------------------------------

    def scan(self) -> ChangeSet:
        """Compute file-level changes vs. the current baseline (no mutation)."""
        old_manifest = self.baseline.load()
        self._baseline_cache = old_manifest

        old_states: dict[str, FileState] = {}
        for path, entry in old_manifest["files"].items():
            if entry.get("exists", True):
                old_states[path] = _entry_to_state(entry)

        new_states = self.scanner.scan()

        added: list[FileChange] = []
        modified: list[FileChange] = []
        deleted: list[FileChange] = []

        for path in sorted(set(old_states) | set(new_states)):
            old = old_states.get(path)
            new = new_states.get(path)
            if old is None and new is not None:
                added.append(FileChange(path, ChangeStatus.ADDED, None, new, self))
            elif old is not None and new is None:
                deleted.append(FileChange(path, ChangeStatus.DELETED, old, None, self))
            elif old is not None and new is not None:
                if old.sha256 != new.sha256:
                    modified.append(
                        FileChange(path, ChangeStatus.MODIFIED, old, new, self)
                    )

        return ChangeSet(added=added, modified=modified, deleted=deleted)

    def commit(self, message: str = "") -> None:
        """Advance the baseline to the current working directory state.

        The manifest write is atomic: :meth:`BaselineManager.save` raises
        *before* the final ``os.replace``, so a failure leaves the on-disk
        baseline completely untouched (transactional integrity).
        """
        prev = self.baseline.load()
        new_manifest = self._build_manifest_from_working(message)
        self.baseline.save(new_manifest)
        # Only push the undo snapshot after a successful commit.
        self.baseline.push_snapshot(prev)
        self._baseline_cache = new_manifest

    def undo(self) -> bool:
        """Roll the baseline back by one commit. Returns True if a rollback
        happened, False if there was nothing to undo.

        This only mutates the baseline; working-directory files are untouched.
        """
        prev = self.baseline.pop_snapshot()
        if prev is None:
            return False
        self.baseline.save(prev)
        self._baseline_cache = prev
        return True

    # ---- content accessors (used lazily by FileChange) ----------------

    def read_baseline_content(self, path: str) -> str | None:
        manifest = (
            self._baseline_cache
            if self._baseline_cache is not None
            else self.baseline.load()
        )
        return self.baseline.get_content(manifest, path)

    def read_working_content(self, path: str) -> str | None:
        abs_path = os.path.join(self.root, path)
        return _read_text(abs_path)

    # ---- internals ----------------------------------------------------

    def _build_manifest_from_working(self, message: str = "") -> dict:
        states = self.scanner.scan()
        files: dict[str, dict] = {}
        for path, st in states.items():
            abs_path = os.path.join(self.root, path)
            content = _read_text(abs_path)
            files[path] = {
                "path": path,
                "exists": True,
                "size": st.size,
                "mtime": st.mtime,
                "sha256": st.sha256,
                "content": content,
            }
        return {
            "version": 1,
            "message": message,
            "committed_at": datetime.now(timezone.utc).isoformat(),
            "files": files,
        }
