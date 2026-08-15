"""Tests for the Python AST symbol parser."""

from __future__ import annotations

from symbol_tracker.models import SymbolType
from symbol_tracker.parsers.python_parser import PythonASTParser


def test_python_syntax_error():
    p = PythonASTParser()
    assert p.parse("def foo(:\n") == []
    assert p.parse("@@@ not python @@@") == []
    assert p.parse("") == []
    assert p.parse("   \n\t  ") == []


def test_parse_module_function_with_signature():
    code = "def foo(a, b, *args, **kwargs):\n    return a + b\n"
    syms = PythonASTParser().parse(code)
    assert len(syms) == 1
    s = syms[0]
    assert s.name == "foo"
    assert s.symbol_type == SymbolType.FUNCTION
    assert s.signature == "def foo(a, b, *args, **kwargs)"
    assert s.start_line == 1
    assert s.end_line == 2
    assert s.body_hash == PythonASTParser.compute_hash(s.content)


def test_parse_async_function():
    code = "async def fetch():\n    await x\n"
    syms = PythonASTParser().parse(code)
    assert len(syms) == 1
    assert syms[0].signature == "async def fetch()"


def test_parse_class_with_qualified_methods():
    code = (
        "class UserService:\n"
        "    def login(self):\n"
        "        return True\n"
        "    async def logout(self):\n"
        "        return False\n"
    )
    syms = {s.name: s for s in PythonASTParser().parse(code)}
    assert "UserService" in syms
    assert syms["UserService"].symbol_type == SymbolType.CLASS
    assert "UserService.login" in syms
    assert syms["UserService.login"].symbol_type == SymbolType.METHOD
    assert syms["UserService.login"].signature == "def login(self)"
    assert "UserService.logout" in syms
    assert syms["UserService.logout"].signature == "async def logout(self)"


def test_body_hash_changes_with_body():
    base = "def foo():\n    return 1\n"
    changed = "def foo():\n    return 2\n"
    a = PythonASTParser().parse(base)[0]
    b = PythonASTParser().parse(changed)[0]
    assert a.body_hash != b.body_hash
    # Signature/name identical -> only body differs.
    assert a.name == b.name
    assert a.signature == b.signature


def test_nested_function_is_qualified():
    code = (
        "def outer():\n"
        "    def inner():\n"
        "        return 1\n"
        "    return inner()\n"
    )
    syms = {s.name: s for s in PythonASTParser().parse(code)}
    assert "outer" in syms
    assert "outer.inner" in syms
    assert syms["outer.inner"].symbol_type == SymbolType.FUNCTION
