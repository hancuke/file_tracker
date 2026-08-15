"""Tests for the recursive file scanner."""

from __future__ import annotations

from filetracker.scanner import FileScanner


def test_scanner_finds_all_text_files(tmp_path):
    (tmp_path / "a.py").write_text("x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.py").write_text("y")
    states = FileScanner(str(tmp_path)).scan()
    assert set(states) == {"a.py", "sub/b.py"}


def test_scanner_respects_exclude_patterns(tmp_path):
    (tmp_path / "a.py").write_text("x")
    (tmp_path / "a.pyc").write_text("x")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "c.pyc").write_text("x")
    states = FileScanner(str(tmp_path), exclude=["*.pyc", "__pycache__"]).scan()
    assert set(states) == {"a.py"}


def test_scanner_excludes_baseline_dir(tmp_path):
    baseline = tmp_path / ".filetracker" / "baseline"
    baseline.mkdir(parents=True)
    (baseline / "manifest.json").write_text("{}")
    (tmp_path / "a.py").write_text("x")
    states = FileScanner(str(tmp_path), baseline_dir=str(baseline)).scan()
    assert set(states) == {"a.py"}
    assert all(".filetracker" not in p for p in states)


def test_scanner_records_metadata(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("hello")
    states = FileScanner(str(tmp_path)).scan()
    st = states["a.py"]
    assert st.exists is True
    assert st.size == 5
    assert st.sha256 is not None
