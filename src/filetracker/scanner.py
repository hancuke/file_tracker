"""Recursive file scanner producing :class:`FileState` snapshots."""

from __future__ import annotations

import fnmatch
import hashlib
import os

from filetracker.models import FileState


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class FileScanner:
    """Walk *root* and collect a :class:`FileState` for every tracked file.

    Paths are stored relative to *root* using POSIX-style separators.
    """

    def __init__(
        self,
        root: str,
        exclude: list[str] | None = None,
        baseline_dir: str | None = None,
    ):
        self.root = os.path.abspath(root)
        self.exclude = list(exclude or [])
        self.baseline_dir = os.path.abspath(baseline_dir) if baseline_dir else None

    def _is_excluded(self, name: str) -> bool:
        return any(fnmatch.fnmatch(name, pat) for pat in self.exclude)

    def _is_baseline_path(self, abs_path: str) -> bool:
        if not self.baseline_dir:
            return False
        return abs_path == self.baseline_dir or abs_path.startswith(
            self.baseline_dir + os.sep
        )

    def scan(self) -> dict[str, FileState]:
        states: dict[str, FileState] = {}
        for dirpath, dirnames, filenames in os.walk(self.root):
            # Prune excluded directories in-place so os.walk skips them.
            kept = []
            for d in dirnames:
                abs_d = os.path.join(dirpath, d)
                if self._is_baseline_path(abs_d) or self._is_excluded(d):
                    continue
                kept.append(d)
            dirnames[:] = kept

            for fname in filenames:
                if self._is_excluded(fname):
                    continue
                abs_path = os.path.join(dirpath, fname)
                if self._is_baseline_path(abs_path):
                    continue
                rel = os.path.relpath(abs_path, self.root).replace(os.sep, "/")
                states[rel] = self._state_for(rel, abs_path)
        return states

    def _state_for(self, rel_path: str, abs_path: str) -> FileState:
        try:
            st = os.stat(abs_path)
        except OSError:
            return FileState(
                path=rel_path, exists=False, size=None, mtime=None, sha256=None
            )
        return FileState(
            path=rel_path,
            exists=True,
            size=st.st_size,
            mtime=st.st_mtime,
            sha256=_sha256_file(abs_path),
        )
