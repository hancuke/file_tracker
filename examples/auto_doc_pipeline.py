"""End-to-end example: auto-update docs from code changes via SymbolTracker.

This is a RUNNABLE demonstration of the "LLM auto-doc update" scenario from
docs/usage.md. It uses a *mock* LLM so it needs no network or API key.

Run with:
    PYTHONPATH=src python examples/auto_doc_pipeline.py
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from filetracker import FileTracker
from symbol_tracker import ParserRegistry, SymbolTracker
from symbol_tracker.models import ChangeStatus
from symbol_tracker.parsers.python_parser import PythonASTParser

# ---------------------------------------------------------------------------
# 0. Helpers: build a minimal-context prompt (Golden Rule #1 & #2)
# ---------------------------------------------------------------------------

# If a function-level diff is larger than this many lines, fall back to sending
# both the old and new full source (e.g. a refactor).
DIFF_LINE_THRESHOLD = 20


def build_minimal_prompt(changes, existing_doc: str) -> str:
    """Assemble a structured prompt with the *minimum* required context."""
    blocks: list[str] = []

    for ch in changes.added + changes.modified + changes.deleted:
        sym = ch.new_symbol if ch.new_symbol is not None else ch.old_symbol
        assert sym is not None
        head = [
            f"[Change]",
            f"- File: {ch.file_path}",
            f"- Symbol: {ch.symbol_name}",
            f"- Change Type: {ch.status.value.upper()}",
        ]

        if ch.status == ChangeStatus.ADDED:
            # Only the new function's signature + full code.
            head.append(f"- Signature: {sym.signature}")
            head.append("```python")
            head.append(sym.content.rstrip("\n"))
            head.append("```")
        elif ch.status == ChangeStatus.DELETED:
            # Only the name + signature; no need to ship the body.
            head.append(f"- Signature: {sym.signature}")
        else:  # MODIFIED -> prefer the function-level diff.
            diff = ch.diff()
            if diff.count("\n") <= DIFF_LINE_THRESHOLD:
                head.append("```diff")
                head.append(diff.rstrip("\n"))
                head.append("```")
            else:
                assert ch.old_symbol and ch.new_symbol
                head.append("```python")
                head.append("# OLD")
                head.append(ch.old_symbol.content.rstrip("\n"))
                head.append("# NEW")
                head.append(ch.new_symbol.content.rstrip("\n"))
                head.append("```")
        blocks.append("\n".join(head))

    code_changes = "\n\n".join(blocks)

    return f"""### 1. Task Instruction
你是一个技术文档专家。请根据提供的代码函数变更，更新对应的系统文档段落。
保持文档的语言风格一致，仅针对受代码变更影响的部分进行修改或补充，不要伪造未提及的逻辑。

---

### 2. Code Changes
{code_changes}

---

### 3. Current Existing Documentation
以下是目前系统中与上述函数相关的文档段落（Markdown 格式）：

<existing_doc>
{existing_doc}
</existing_doc>

---

### 4. Output Response Format
请按照以下 JSON 格式输出更新后的结果（不要添加任何多余废话）：

{{
  "updated_doc_section": "更新后的完整 Markdown 文档段落...",
  "change_summary": "简要说明本次文档修改了哪些地方"
}}
"""


# ---------------------------------------------------------------------------
# 1. Mock LLM + response handling (validation -> patch -> commit)
# ---------------------------------------------------------------------------

def call_llm(prompt: str) -> str:
    """Mock LLM: returns a fixed, valid JSON response for the demo."""
    updated = (
        "### 1.2 用户邮箱变更接口\n"
        "用户可以通过 `update_email` 接口更新绑定邮箱。\n"
        "**参数说明**：\n"
        "- `user_id`: 用户唯一ID\n"
        "- `new_email`: 新邮箱地址（必须通过 `validate_email_format` 校验）\n\n"
        "**新增**：`verify_code(user_id, code)` 用于校验邮箱验证码。\n\n"
        "**异常处理**：\n"
        "- 邮箱格式不正确时抛出 `ValueError`。\n"
        "- 变更后会调用 `send_verification_email` 发送验证邮件。"
    )
    return json.dumps(
        {
            "updated_doc_section": updated,
            "change_summary": "补充 verify_code 说明，更新邮箱格式校验逻辑描述。",
        },
        ensure_ascii=False,
    )


def is_valid_response(raw: str):
    """Parse + guardrail the LLM response. Returns the payload or None."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    section = data.get("updated_doc_section")
    summary = data.get("change_summary")
    # Content guardrail: reject empty / non-string results.
    if not isinstance(section, str) or not section.strip():
        return None
    if not isinstance(summary, str) or not summary.strip():
        return None
    return data


DOC_START = "<!-- DOC_START -->"
DOC_END = "<!-- DOC_END -->"


def apply_doc_updates(doc_path: Path, new_section: str) -> None:
    """Patch only the marked section of the Markdown doc (local replace)."""
    text = doc_path.read_text(encoding="utf-8")
    start = text.index(DOC_START) + len(DOC_START)
    end = text.index(DOC_END)
    patched = text[:start] + "\n" + new_section + "\n" + text[end:]
    doc_path.write_text(patched, encoding="utf-8")


# ---------------------------------------------------------------------------
# 2. The pipeline (mirrors docs/usage.md §3.4)
# ---------------------------------------------------------------------------

def process_pipeline(file_tracker: FileTracker, symbol_tracker: SymbolTracker, doc_path: Path):
    symbol_changes = symbol_tracker.scan_symbols()
    if not symbol_changes.has_changes:
        print("No symbol-level changes detected. Skip processing.")
        return

    existing_doc = doc_path.read_text(encoding="utf-8")
    prompt = build_minimal_prompt(symbol_changes, existing_doc)
    print("===== PROMPT (first 600 chars) =====")
    print(prompt[:600] + " ...")

    llm_response = call_llm(prompt)
    payload = is_valid_response(llm_response)
    if payload is None:
        print("LLM 响应无效，终止更新，Baseline 保持不变。")
        return

    apply_doc_updates(doc_path, payload["updated_doc_section"])

    # Only commit after the doc was successfully updated & validated.
    file_tracker.commit(message=f"Auto doc update: {payload['change_summary']}")
    print("文档更新完成，Baseline 已推进！")


# ---------------------------------------------------------------------------
# 3. Scenario setup + assertions
# ---------------------------------------------------------------------------

SRC_V1 = (
    "def update_email(user_id, new_email):\n"
    "    if \"@\" not in new_email:\n"
    "        raise ValueError(\"Invalid email\")\n"
    "    return True\n"
)

SRC_V2 = (
    "def validate_email_format(email):\n"
    "    return \"@\" in email and \".\" in email\n"
    "\n"
    "def update_email(user_id, new_email):\n"
    "    if not validate_email_format(new_email):\n"
    "        raise ValueError(\"Invalid email\")\n"
    "    send_verification_email(user_id, new_email)\n"
    "    return True\n"
    "\n"
    "def verify_code(user_id, code):\n"
    "    \"\"\"验证用户输入的邮箱验证码\"\"\"\n"
    "    return redis_client.get(f\"code:{user_id}\") == code\n"
)

DOC_V1 = (
    "# API 文档\n"
    f"{DOC_START}\n"
    "### 1.2 用户邮箱变更接口\n"
    "用户可以通过 `update_email` 接口更新绑定邮箱。\n"
    "**参数说明**：\n"
    "- `user_id`: 用户唯一ID\n"
    "- `new_email`: 新邮箱地址（必须包含 @ 符号）\n\n"
    "**异常处理**：\n"
    "- 邮箱格式不正确时抛出 `ValueError`。\n"
    f"{DOC_END}\n"
)


def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="ft_demo_"))
    src_file = root / "src" / "services" / "user_service.py"
    doc_file = root / "docs" / "api.md"
    src_file.parent.mkdir(parents=True)
    doc_file.parent.mkdir(parents=True)

    # Baseline: v1 source + v1 doc.
    src_file.write_text(SRC_V1, encoding="utf-8")
    doc_file.write_text(DOC_V1, encoding="utf-8")

    file_tracker = FileTracker(root=str(root))
    registry = ParserRegistry()
    registry.register(".py", PythonASTParser())
    symbol_tracker = SymbolTracker(file_tracker, registry)

    # First run: nothing changed yet -> baseline established.
    file_tracker.scan()
    file_tracker.commit(message="initial")

    # Apply the code change (v1 -> v2).
    src_file.write_text(SRC_V2, encoding="utf-8")

    cs = symbol_tracker.scan_symbols()
    added = {c.symbol_name for c in cs.added}
    modified = {c.symbol_name for c in cs.modified}
    print("ADDED:", added)
    print("MODIFIED:", modified)
    assert "UserService" not in added  # module-level, unqualified
    assert "verify_code" in added
    assert "update_email" in modified

    doc_before = doc_file.read_text(encoding="utf-8")
    process_pipeline(file_tracker, symbol_tracker, doc_file)
    doc_after = doc_file.read_text(encoding="utf-8")
    assert doc_before != doc_after, "doc should have been patched"
    assert "verify_code" in doc_after, "new function must appear in doc"

    # After commit, a fresh scan must be clean (baseline advanced).
    assert file_tracker.scan().has_changes is False
    print("\nALL ASSERTIONS PASSED")


if __name__ == "__main__":
    main()
