"""Data models for symbol/function-level change tracking."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from filetracker.diff import unified_diff
from filetracker.models import ChangeStatus


class SymbolType(Enum):
    FUNCTION = "function"
    METHOD = "method"
    CLASS = "class"


@dataclass(frozen=True)
class SymbolState:
    """Immutable snapshot of a single code symbol (function/method/class)."""

    name: str  # Fully-qualified name, e.g. "UserService.login" or "process_data"
    symbol_type: SymbolType
    signature: str  # Function/method definition signature
    content: str  # Complete source of the symbol body
    body_hash: str  # SHA-256 of the symbol body
    start_line: int  # 1-based start line
    end_line: int  # 1-based end line (inclusive)


@dataclass
class SymbolChange:
    file_path: str
    symbol_name: str
    status: ChangeStatus
    old_symbol: SymbolState | None
    new_symbol: SymbolState | None

    def diff(self) -> str:
        """Generate a body-level Unified Diff for this symbol change."""
        old = self.old_symbol.content if self.old_symbol else ""
        new = self.new_symbol.content if self.new_symbol else ""
        return unified_diff(
            old, new, from_path=self.file_path, to_path=self.file_path
        )


@dataclass
class SymbolChangeSet:
    added: list[SymbolChange]
    modified: list[SymbolChange]
    deleted: list[SymbolChange]

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.modified or self.deleted)

    def to_llm_text(self) -> str:
        """Format the change set as structured Markdown for an LLM prompt."""
        if not self.has_changes:
            return "No symbol-level changes detected."

        parts: list[str] = []
        for title, items in (
            ("Added", self.added),
            ("Modified", self.modified),
            ("Deleted", self.deleted),
        ):
            if not items:
                continue
            parts.append(f"## {title} Symbols")
            for ch in items:
                sym = ch.new_symbol if ch.new_symbol is not None else ch.old_symbol
                if sym is None:
                    continue
                parts.append(f"### {sym.symbol_type.value}: `{ch.symbol_name}`")
                parts.append(f"- file: `{ch.file_path}`")
                parts.append(f"- signature: `{sym.signature}`")
                parts.append(f"- lines: {sym.start_line}-{sym.end_line}")
                if ch.status == ChangeStatus.MODIFIED:
                    parts.append("```diff")
                    parts.append(ch.diff().rstrip("\n"))
                    parts.append("```")
                else:
                    parts.append("```python")
                    parts.append(sym.content.rstrip("\n"))
                    parts.append("```")
                parts.append("")
        return "\n".join(parts).rstrip("\n") + "\n"
