"""Data models for physical file-level change tracking."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from filetracker.diff import unified_diff

if TYPE_CHECKING:
    from filetracker.tracker import FileTracker


class ChangeStatus(Enum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"


@dataclass(frozen=True)
class FileState:
    """Immutable snapshot of a file's metadata. Content is not stored here;
    it is lazily loaded via the owning :class:`FileTracker`."""

    path: str
    exists: bool
    size: int | None
    mtime: float | None
    sha256: str | None


@dataclass
class FileChange:
    path: str
    status: ChangeStatus
    old: FileState | None
    new: FileState | None
    tracker: "FileTracker"

    def old_content(self) -> str | None:
        """Lazily load the Baseline text content of this file."""
        return self.tracker.read_baseline_content(self.path)

    def new_content(self) -> str | None:
        """Lazily load the current Working-Dir text content of this file."""
        return self.tracker.read_working_content(self.path)

    def diff(self) -> str:
        """Generate a textual Unified Diff between old and new content."""
        old = self.old_content() or ""
        new = self.new_content() or ""
        return unified_diff(old, new, self.path, self.path)


@dataclass
class ChangeSet:
    added: list[FileChange]
    modified: list[FileChange]
    deleted: list[FileChange]

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.modified or self.deleted)

    @property
    def total(self) -> int:
        return len(self.added) + len(self.modified) + len(self.deleted)

    def __iter__(self):
        return iter(self.added + self.modified + self.deleted)
