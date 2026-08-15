"""Tests for the filetracker CLI (scan / commit / undo / symbols)."""

from __future__ import annotations

import os

from filetracker.cli import main


def _write(root, name, text):
    p = root / name
    p.write_bytes(text.encode("utf-8"))
    return p


def test_cli_scan_commit_undo(tmp_path, capsys):
    _write(tmp_path, "a.py", "x")
    assert main(["scan", "--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "1 added" in out
    assert "[added] a.py" in out

    # Commit #1.
    assert main(["commit", "--root", str(tmp_path), "-m", "init"]) == 0
    assert "Baseline advanced." in capsys.readouterr().out

    _write(tmp_path, "a.py", "xy")
    assert main(["scan", "--root", str(tmp_path)]) == 0
    assert "1 modified" in capsys.readouterr().out

    # Commit #2 (baseline now == "xy").
    assert main(["commit", "--root", str(tmp_path), "-m", "second"]) == 0
    capsys.readouterr()

    # Move the working file forward again, then undo: baseline rolls back to
    # after commit #1 ("x"), so the change is visible once more as modified.
    _write(tmp_path, "a.py", "xyz")
    assert main(["undo", "--root", str(tmp_path)]) == 0
    assert "Baseline rolled back" in capsys.readouterr().out

    assert main(["scan", "--root", str(tmp_path)]) == 0
    assert "1 modified" in capsys.readouterr().out


def test_cli_undo_nothing(tmp_path, capsys):
    assert main(["undo", "--root", str(tmp_path)]) == 0
    assert "Nothing to undo." in capsys.readouterr().out


def test_cli_symbols_compact(tmp_path, capsys):
    _write(
        tmp_path,
        "m.py",
        "def foo():\n    return 1\n",
    )
    assert main(["scan", "--root", str(tmp_path)]) == 0
    capsys.readouterr()
    assert main(["commit", "--root", str(tmp_path), "-m", "init"]) == 0
    capsys.readouterr()

    _write(
        tmp_path,
        "m.py",
        "def foo():\n    return 2\n\ndef bar():\n    return 3\n",
    )
    assert main(["symbols", "--root", str(tmp_path), "--format", "compact"]) == 0
    out = capsys.readouterr().out
    assert "[MODIFIED] m.py :: foo" in out
    assert "[ADDED]    m.py :: bar" in out


def test_cli_symbols_llm_format(tmp_path, capsys):
    _write(tmp_path, "m.py", "def foo():\n    return 1\n")
    assert main(["scan", "--root", str(tmp_path)]) == 0
    capsys.readouterr()
    assert main(["commit", "--root", str(tmp_path), "-m", "init"]) == 0
    capsys.readouterr()
    _write(tmp_path, "m.py", "def foo():\n    return 2\n")
    assert main(["symbols", "--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "## Modified Symbols" in out
    assert "def foo()" in out


def test_cli_symbols_no_changes(tmp_path, capsys):
    _write(tmp_path, "m.py", "def foo():\n    return 1\n")
    assert main(["scan", "--root", str(tmp_path)]) == 0
    capsys.readouterr()
    assert main(["commit", "--root", str(tmp_path), "-m", "init"]) == 0
    capsys.readouterr()
    assert main(["symbols", "--root", str(tmp_path)]) == 0
    assert "No symbol-level changes detected." in capsys.readouterr().out
