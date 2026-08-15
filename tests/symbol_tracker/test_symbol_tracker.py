"""Tests for the SymbolTracker change-detection pipeline."""

from __future__ import annotations

from filetracker.models import ChangeStatus
from filetracker.tracker import FileTracker
from symbol_tracker.parsers.python_parser import PythonASTParser
from symbol_tracker.registry import ParserRegistry
from symbol_tracker.tracker import SymbolTracker


def _make_tracker(tmp_path):
    (tmp_path / "m.py").write_text("def placeholder():\n    pass\n")
    ft = FileTracker(root=str(tmp_path))
    ft.scan()
    ft.commit()
    registry = ParserRegistry()
    registry.register(".py", PythonASTParser())
    return ft, SymbolTracker(ft, registry)


def test_function_rename(tmp_path):
    ft, st = _make_tracker(tmp_path)
    # Rename `placeholder` -> `renamed`.
    (tmp_path / "m.py").write_text("def renamed():\n    pass\n")
    cs = st.scan_symbols()
    added = {c.symbol_name for c in cs.added}
    deleted = {c.symbol_name for c in cs.deleted}
    assert "renamed" in added
    assert "placeholder" in deleted
    assert len(cs.modified) == 0
    assert cs.added[0].status == ChangeStatus.ADDED
    assert cs.deleted[0].status == ChangeStatus.DELETED


def test_function_body_modified(tmp_path):
    ft, st = _make_tracker(tmp_path)
    # Only change internal logic; signature/name stay the same.
    (tmp_path / "m.py").write_text("def placeholder():\n    return 42\n")
    cs = st.scan_symbols()
    assert len(cs.modified) == 1
    assert cs.modified[0].symbol_name == "placeholder"
    assert cs.modified[0].status == ChangeStatus.MODIFIED
    assert len(cs.added) == 0
    assert len(cs.deleted) == 0
    # The diff must reflect the body change.
    assert "42" in cs.modified[0].diff()


def test_added_and_deleted_symbols(tmp_path):
    ft, st = _make_tracker(tmp_path)
    (tmp_path / "m.py").write_text(
        "def another():\n    return 1\n"
    )
    cs = st.scan_symbols()
    assert {c.symbol_name for c in cs.added} == {"another"}
    assert {c.symbol_name for c in cs.deleted} == {"placeholder"}


def test_no_changes_returns_empty(tmp_path):
    ft, st = _make_tracker(tmp_path)
    cs = st.scan_symbols()
    assert cs.has_changes is False


def test_skips_files_without_parser(tmp_path):
    (tmp_path / "m.py").write_text("def f():\n    pass\n")
    (tmp_path / "doc.txt").write_text("hello")
    ft = FileTracker(root=str(tmp_path))
    ft.scan()
    ft.commit()
    # Only register a parser for .py; the .txt change must be ignored.
    (tmp_path / "doc.txt").write_text("hello world")
    registry = ParserRegistry()
    registry.register(".py", PythonASTParser())
    st = SymbolTracker(ft, registry)
    cs = st.scan_symbols()
    assert cs.has_changes is False


def test_to_llm_text_format(tmp_path):
    ft, st = _make_tracker(tmp_path)
    (tmp_path / "m.py").write_text("def placeholder():\n    return 42\n")
    cs = st.scan_symbols()
    text = cs.to_llm_text()
    assert "Modified" in text
    assert "placeholder" in text
    assert "42" in text
