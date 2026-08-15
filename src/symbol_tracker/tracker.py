"""SymbolTracker: symbol/function-level change detection on top of FileTracker."""

from __future__ import annotations

from filetracker.models import ChangeStatus
from filetracker.tracker import FileTracker

from symbol_tracker.base_parser import SymbolParser
from symbol_tracker.models import SymbolChange, SymbolChangeSet, SymbolState
from symbol_tracker.registry import ParserRegistry


class SymbolTracker:
    def __init__(
        self,
        file_tracker: FileTracker,
        registry: ParserRegistry | None = None,
    ):
        self.file_tracker = file_tracker
        self.registry = registry or ParserRegistry()

    def scan_symbols(self) -> SymbolChangeSet:
        # 1. Trigger the physical file-level scan (read-only vs. baseline).
        file_changes = self.file_tracker.scan()

        added_symbols: list[SymbolChange] = []
        modified_symbols: list[SymbolChange] = []
        deleted_symbols: list[SymbolChange] = []

        for change in file_changes:
            parser = self.registry.get_parser(change.path)
            if not parser:
                # No matching syntax parser -> skip symbol-level analysis.
                continue

            old_map = self._extract_symbol_map(parser, change.old_content())
            new_map = self._extract_symbol_map(parser, change.new_content())

            # 2. Detect added / modified symbols.
            for name, new_sym in new_map.items():
                if name not in old_map:
                    added_symbols.append(
                        SymbolChange(
                            file_path=change.path,
                            symbol_name=name,
                            status=ChangeStatus.ADDED,
                            old_symbol=None,
                            new_symbol=new_sym,
                        )
                    )
                elif new_sym.body_hash != old_map[name].body_hash:
                    modified_symbols.append(
                        SymbolChange(
                            file_path=change.path,
                            symbol_name=name,
                            status=ChangeStatus.MODIFIED,
                            old_symbol=old_map[name],
                            new_symbol=new_sym,
                        )
                    )

            # 3. Detect deleted symbols.
            for name, old_sym in old_map.items():
                if name not in new_map:
                    deleted_symbols.append(
                        SymbolChange(
                            file_path=change.path,
                            symbol_name=name,
                            status=ChangeStatus.DELETED,
                            old_symbol=old_sym,
                            new_symbol=None,
                        )
                    )

        return SymbolChangeSet(
            added=added_symbols,
            modified=modified_symbols,
            deleted=deleted_symbols,
        )

    def _extract_symbol_map(
        self, parser: SymbolParser, content: str | None
    ) -> dict[str, SymbolState]:
        if not content:
            return {}
        symbols = parser.parse(content)
        return {s.name: s for s in symbols}
