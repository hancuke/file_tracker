# 使用指南与测试用例文档

本文档帮助用户快速上手 `filetracker`（文件级追踪）与 `symbol_tracker`（函数/符号级追踪）两个库，并重点演示如何将它们落地到 **“根据代码变更自动更新文档”** 的实际工程中。

配套可运行示例见 [`examples/auto_doc_pipeline.py`](examples/auto_doc_pipeline.py)（使用 Mock LLM，无需联网即可跑通），请以它为“端到端测试用例”直接运行验证：

```bash
PYTHONPATH=src python examples/auto_doc_pipeline.py
```

---

## 0. 环境准备

```bash
# 在项目根目录（含 pyproject.toml）安装为可编辑包
pip install -e .

# 仅运行测试
pip install pytest && pytest
```

安装后可直接 `import filetracker` / `import symbol_tracker`；未安装时可用 `PYTHONPATH=src` 运行任何脚本。

---

## 1. 文件级：FileTracker 基本用法

`FileTracker` 负责在物理文件层面检测 `ADDED / MODIFIED / DELETED`，并提供 **事务化** 的 Baseline 提交与回滚。

### 1.1 Python API 测试用例

```python
from filetracker import FileTracker

tracker = FileTracker(root="./src", exclude=["*.pyc", "__pycache__", ".git"])

# 第一次扫描：还没有 Baseline，所有文件视为 ADDED
changes = tracker.scan()
print(changes.total)          # -> 文件数量
print(changes.added[0].path)  # -> 某个文件路径

# 推进 Baseline（原子写入 manifest.json）
tracker.commit(message="initial import")

# 修改某个文件后再次扫描
changes = tracker.scan()
print(changes.modified[0].status.value)   # -> "modified"
print(changes.modified[0].diff())         # -> 文本 Unified Diff

# 回滚最近一次提交（仅影响 Baseline，不动工作区源码）
tracker.undo()
```

**预期行为（对应 `tests/filetracker/test_tracker.py`）**

| 用例 | 输入 | 预期 |
| --- | --- | --- |
| 首次扫描 | 空 Baseline + 1 个文件 | `total == 1`，状态 `added` |
| 提交后扫描 | 内容不变 | `has_changes is False` |
| 修改后扫描 | 文件内容变化 | `len(modified) == 1` |
| 删除后扫描 | 文件被删 | `len(deleted) == 1` |
| 提交失败回滚 | `baseline.save` 抛异常 | Baseline 保持不变 |
| 两次提交后 `undo()` | — | 回滚到第一次提交后的状态，工作区源码不变 |

### 1.2 CLI 完整使用指南

CLI 入口为 `filetracker.cli`，所有子命令共享两个通用参数：

| 参数 | 说明 |
| --- | --- |
| `--root` | 要追踪的根目录，默认 `.` |
| `--exclude` | 多个 glob 模式，如 `--exclude "*.pyc" "__pycache__"` |

> 若已 `pip install -e .`，可直接用 `filetracker` 代替 `python -m filetracker.cli`。

#### 子命令一览

| 子命令 | 作用 | 是否改动 Baseline |
| --- | --- | --- |
| `scan` | 列出相对 Baseline 的文件级变更（只读） | 否 |
| `commit` | 将当前工作区状态写入 Baseline | 是（原子） |
| `undo` | 回滚最近一次提交 | 是（仅动 Baseline，不动源码） |
| `symbols` | 列出函数/符号级变更（Python） | 否 |

退出码：成功 `0`；`undo` 时无内容可回滚也返回 `0`（打印 `Nothing to undo.`）。可据此在脚本里判断是否继续。

#### 1) `scan` —— 只读扫描

```bash
python -m filetracker.cli scan --root ./src
# 尚无 Baseline 时，所有文件视为 added：
#   Changes: 1 added, 0 modified, 0 deleted.
#     [added] services/user_service.py
```

修改文件后再扫描：

```bash
python -m filetracker.cli scan --root ./src
#   Changes: 0 added, 1 modified, 0 deleted.
#     [modified] services/user_service.py
```

#### 2) `commit` —— 推进 Baseline

```bash
python -m filetracker.cli commit --root ./src -m "initial import"
#   Baseline advanced.
```

`-m/--message` 会记录在 `manifest.json` 的 `message` 字段中（见 §1.1）。

#### 3) `undo` —— 回滚

```bash
python -m filetracker.cli undo --root ./src
#   Baseline rolled back by one commit.

# 没有可回滚内容时：
#   Nothing to undo.
```

#### 4) `symbols` —— 函数级变更（用于文档自动更新场景）

`symbols` 在 `scan` 之上叠加 Python AST 解析，输出“改了哪些函数”。这是把代码变更喂给 LLM 的关键一步。

```bash
# 紧凑模式：每行一个变更，便于脚本解析
python -m filetracker.cli symbols --root ./src --format compact
#   [ADDED]    services/user_service.py :: validate_email_format
#   [ADDED]    services/user_service.py :: verify_code
#   [MODIFIED] services/user_service.py :: update_email

# llm 模式（默认）：结构化 Markdown，可直接粘进 Prompt 的 “Code Changes” 段
python -m filetracker.cli symbols --root ./src
#   ## Added Symbols
#   ### function: `validate_email_format`
#   - file: `services/user_service.py`
#   - signature: `def validate_email_format(email)`
#   - lines: 1-2
#   ```python
#   def validate_email_format(email):
#       return "@" in email and "." in email
#   ```
#   ### function: `verify_code`
#   ...
#   ## Modified Symbols
#   ### function: `update_email`
#   ...
```

> `--format llm` 的输出与 `SymbolChangeSet.to_llm_text()` 完全一致，可作为 §3 “自动更新文档” Prompt 的 **Code Changes** 部分直接复用。

#### 5) 端到端工作流（真实可复现）

下面用同一个 `services/user_service.py` 演示从初始化到回滚的完整闭环（输出已实跑验证）：

```bash
# 准备 v1 源码
cat > src/services/user_service.py <<'EOF'
def update_email(user_id, new_email):
    if "@" not in new_email:
        raise ValueError("Invalid email")
    return True
EOF

python -m filetracker.cli scan --root ./src
#   Changes: 1 added, 0 modified, 0 deleted.
#     [added] services/user_service.py

python -m filetracker.cli commit --root ./src -m "initial import"
#   Baseline advanced.

# 升级到 v2：新增两个函数、改写 update_email
cat > src/services/user_service.py <<'EOF'
def validate_email_format(email):
    return "@" in email and "." in email

def update_email(user_id, new_email):
    if not validate_email_format(new_email):
        raise ValueError("Invalid email")
    send_verification_email(user_id, new_email)
    return True

def verify_code(user_id, code):
    """验证用户输入的邮箱验证码"""
    return redis_client.get(f"code:{user_id}") == code
EOF

python -m filetracker.cli symbols --root ./src --format compact
#   [ADDED]    services/user_service.py :: validate_email_format
#   [ADDED]    services/user_service.py :: verify_code
#   [MODIFIED] services/user_service.py :: update_email

python -m filetracker.cli commit --root ./src -m "add verify_code"
#   Baseline advanced.

python -m filetracker.cli undo --root ./src
#   Baseline rolled back by one commit.

python -m filetracker.cli scan --root ./src
#   Changes: 0 added, 1 modified, 0 deleted.   <- 回滚后再次看到 v2 的改动
#     [modified] services/user_service.py
```

> 把上面第 4 步的 `symbols --format llm` 输出，连同文档对应段落，套进 §3.3 的 Prompt 模板，即可驱动 LLM 更新文档；只有文档校验通过后才执行 `commit`（Gold Rule #3）。

---

## 2. 符号级：SymbolTracker 函数变更

`SymbolTracker` 组合在 `FileTracker` 之上：先触发物理扫描，再对发生变动的 `.py` 文件按需做 AST 切片，按 **函数名 + 函数体 Hash** 识别 `ADDED / MODIFIED / DELETED`。

```python
from filetracker import FileTracker
from symbol_tracker import ParserRegistry, SymbolTracker
from symbol_tracker.parsers.python_parser import PythonASTParser

file_tracker = FileTracker(root="./src")
registry = ParserRegistry()
registry.register(".py", PythonASTParser())   # 注册 Python 解析器

symbol_tracker = SymbolTracker(file_tracker, registry)

symbol_changes = symbol_tracker.scan_symbols()
if not symbol_changes.has_changes:
    print("No function-level changes detected. Skip processing.")
    return

for ch in symbol_changes.added:
    print("ADDED  ", ch.symbol_name, ch.new_symbol.signature)
for ch in symbol_changes.modified:
    print("MODIFIED", ch.symbol_name)
    print(ch.diff())                          # 函数级 Unified Diff
for ch in symbol_changes.deleted:
    print("DELETED", ch.symbol_name)
```

**关键数据结构**（见 `src/symbol_tracker/models.py`）

- `SymbolState`：`name`（完整限定名，如 `UserService.login`）、`symbol_type`、`signature`、`content`（完整源码，含 Docstring）、`body_hash`、`start_line`、`end_line`。
- `SymbolChange`：`file_path`、`symbol_name`、`status`、`old_symbol`、`new_symbol`、`.diff()`。
- `SymbolChangeSet`：`.added` / `.modified` / `.deleted` / `.has_changes` / `.to_llm_text()`。

**预期行为（对应 `tests/symbol_tracker/*`）**

| 用例 | 预期 |
| --- | --- |
| `test_function_rename` | 重命名 → 旧函数 `DELETED` + 新函数 `ADDED` |
| `test_function_body_modified` | 仅改函数体内逻辑 → `MODIFIED` 且 `body_hash` 变化 |
| `test_python_syntax_error` | 源码语法错误时 `parse()` 返回 `[]` 不崩溃 |
| `test_nested_function_is_qualified` | 嵌套函数被捕获并限定命名（`outer.inner`） |

> 命名约定：`PythonASTParser` 对类成员输出 `ClassName.method` 的限定名；方法（`METHOD`）与模块级/嵌套函数（`FUNCTION`）区分；类本身作为 `CLASS` 输出。

---

## 3. 端到端测试用例：基于代码变更自动更新文档

下面把第 2 节的能力落到“高效文档更新”场景。核心思路与你的工程规范一致：

> **送给 LLM 的上下文越精准、噪声越少，输出越稳定、Token 越省。**

### 3.1 场景设定（`examples/auto_doc_pipeline.py`）

一个临时工程包含：

- `src/services/user_service.py`：初始版本 `v1`（仅 `update_email`），变更为 `v2`（新增 `validate_email_format`、`verify_code`，并改写 `update_email` 校验逻辑）。
- `docs/api.md`：其中用 `<!-- DOC_START --> ... <!-- DOC_END -->` 标记了“用户邮箱变更接口”段落，作为 **局部替换** 的目标锚点。

### 3.2 核心数据选型（只给 LLM 最少必要的 4 类数据）

| 数据 | 提取方式（来自 `SymbolChange`） |
| --- | --- |
| ① 变更元数据 | `ch.file_path`、`ch.symbol_name`、`ch.status.value` |
| ② 代码上下文 | `ADDED`：`new_symbol.signature` + `new_symbol.content`；`DELETED`：仅 `old_symbol.signature`/`name`；`MODIFIED`：优先 `ch.diff()`（函数级 Diff），过大时回退完整新旧代码 |
| ③ 目标文档段落 | 读取 `docs/api.md` 中标记段落，**只送这一段**，不送整份大文档 |
| ④ 注释/Docstring（可选） | `new_symbol.content` 已包含 Docstring，天然随代码上下文提供 |

对应的最小上下文构造（`examples/auto_doc_pipeline.py::build_minimal_prompt`）：

```python
DIFF_LINE_THRESHOLD = 20  # diff 行数超过此阈值则回退完整代码

def build_minimal_prompt(changes, existing_doc: str) -> str:
    blocks = []
    for ch in changes.added + changes.modified + changes.deleted:
        sym = ch.new_symbol or ch.old_symbol
        head = [f"[Change]",
                f"- File: {ch.file_path}",
                f"- Symbol: {ch.symbol_name}",
                f"- Change Type: {ch.status.value.upper()}"]
        if ch.status == ChangeStatus.ADDED:
            head += [f"- Signature: {sym.signature}", "```python",
                     sym.content.rstrip("\n"), "```"]
        elif ch.status == ChangeStatus.DELETED:
            head += [f"- Signature: {sym.signature}"]   # 不给函数体
        else:  # MODIFIED
            diff = ch.diff()
            if diff.count("\n") <= DIFF_LINE_THRESHOLD:
                head += ["```diff", diff.rstrip("\n"), "```"]
            else:
                head += ["```python", "# OLD", ch.old_symbol.content.rstrip("\n"),
                         "# NEW", ch.new_symbol.content.rstrip("\n"), "```"]
        blocks.append("\n".join(head))
    code_changes = "\n\n".join(blocks)
    # 按 “角色指令 → 变更数据 → 原文档段落 → 输出格式约束” 顺序组装
    return TEMPLATE.format(code_changes=code_changes, existing_doc=existing_doc)
```

### 3.3 Prompt 模板与组装顺序

严格遵循 **“任务指令 → 代码变更 → 现有文档段落 → 输出格式约束”** 的顺序，并要求 LLM 返回结构化 JSON，便于代码自动解析：

```text
### 1. Task Instruction
你是一个技术文档专家。请根据提供的代码函数变更，更新对应的系统文档段落。
保持文档的语言风格一致，仅针对受代码变更影响的部分进行修改或补充，不要伪造未提及的逻辑。

---

### 2. Code Changes
[Change]
- File: src/services/user_service.py
- Symbol: update_email
- Change Type: MODIFIED
```diff
-   if "@" not in new_email:
+   if not validate_email_format(new_email):
        raise ValueError("Invalid email")
+   send_verification_email(user_id, new_email)
```

[Change]
- File: src/services/user_service.py
- Symbol: verify_code
- Change Type: ADDED
- Signature: def verify_code(user_id, code)
```python
def verify_code(user_id, code):
    """验证用户输入的邮箱验证码"""
    return redis_client.get(f"code:{user_id}") == code
```

---

### 3. Current Existing Documentation
<existing_doc>
### 1.2 用户邮箱变更接口
用户可以通过 `update_email` 接口更新绑定邮箱。
...
</existing_doc>

---

### 4. Output Response Format
{
  "updated_doc_section": "更新后的完整 Markdown 文档段落...",
  "change_summary": "简要说明本次文档修改了哪些地方"
}
```

（直接调用 `symbol_changes.to_llm_text()` 可快速得到内置的结构化摘要；若需按 3.2 的“最少上下文”策略裁剪，使用上面的 `build_minimal_prompt`。）

### 3.4 响应处理与事务落盘（校验 → 替换 → 提交）

处理 LLM 响应的核心是 **“校验-替换-事务提交”** 闭环：错误的响应绝不污染文档，也绝不推进 Baseline。

```python
def is_valid_response(raw: str):
    """JSON 结构解析 + 内容合理性校验（Guardrail）。"""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    section = data.get("updated_doc_section")
    summary = data.get("change_summary")
    if not isinstance(section, str) or not section.strip():
        return None                      # 空内容 -> 拒绝
    if not isinstance(summary, str) or not summary.strip():
        return None
    return data

def apply_doc_updates(doc_path: Path, new_section: str) -> None:
    """局部替换：只写回标记段落，不碰整份文件。"""
    text = doc_path.read_text(encoding="utf-8")
    start = text.index("<!-- DOC_START -->") + len("<!-- DOC_START -->")
    end = text.index("<!-- DOC_END -->")
    doc_path.write_text(text[:start] + "\n" + new_section + "\n" + text[end:],
                        encoding="utf-8")

def process_pipeline(file_tracker, symbol_tracker, doc_path):
    symbol_changes = symbol_tracker.scan_symbols()
    if not symbol_changes.has_changes:
        return
    prompt = build_minimal_prompt(symbol_changes, doc_path.read_text())
    llm_response = call_llm(prompt)               # 真实场景替换为你的 LLM 调用

    payload = is_valid_response(llm_response)
    if payload is None:
        print("LLM 响应无效，终止更新，Baseline 保持不变。")
        return

    apply_doc_updates(doc_path, payload["updated_doc_section"])

    # 只有文档成功更新且通过校验后，才提交 Baseline
    file_tracker.commit(message=f"Auto doc update: {payload['change_summary']}")
    print("文档更新完成，Baseline 已推进！")
```

> **结构化输出增强（可选）**：若环境已安装 `pydantic`，可用其做强类型校验（替代手写 `is_valid_response` 的 JSON 解析部分）：
>
> ```python
> from pydantic import BaseModel, Field
> class LLMDocResponse(BaseModel):
>     updated_doc_section: str = Field(description="更新后的 Markdown 文档段落")
>     change_summary: str = Field(description="文档变更总结")
> # response_data = LLMDocResponse.model_validate_json(raw_llm_response)
> ```
> 注意：`pydantic` 不是本库依赖，示例脚本用标准库 `json` 即可跑通。

### 3.5 运行与预期结果

```bash
PYTHONPATH=src python examples/auto_doc_pipeline.py
```

预期输出（节选）：

```text
ADDED: {'validate_email_format', 'verify_code'}
MODIFIED: {'update_email'}
===== PROMPT (first 600 chars) =====
### 1. Task Instruction
你是一个技术文档专家。...
=== Code Changes ===
[Change]
- File: src/services/user_service.py
- Symbol: update_email
- Change Type: MODIFIED
```diff
...
文档更新完成，Baseline 已推进！
ALL ASSERTIONS PASSED
```

脚本内置断言验证了三件事：

1. `scan_symbols()` 正确识别 `verify_code` / `validate_email_format` 为 `ADDED`、`update_email` 为 `MODIFIED`；
2. `docs/api.md` 中被标记段落被成功局部替换（含 `verify_code` 说明）；
3. 提交后再次 `scan()` 结果为空（Baseline 已推进）。

---

## 4. 高效处理的 3 条 Golden Rules（速查）

1. **按需提供（Minimal Context）**：只给改动的函数（Diff 或新源码）和它对应的文档段落，绝不把未修改的代码与无关文档发给 LLM。→ 用 `build_minimal_prompt` 与 `.to_llm_text()`。
2. **结构化约束（Structured Format）**：Prompt 中明确 JSON 输出格式，便于自动解析。→ `is_valid_response` / `pydantic`。
3. **失败回滚（Fail-Safe Commit）**：把“文档更新”当事务——只有文档成功修改并通过校验，才调用 `file_tracker.commit()`，否则保留代码变动状态等待重试。→ `process_pipeline`。

### API 速查表

| 目标 | 调用 |
| --- | --- |
| 物理文件扫描 | `FileTracker(root, exclude=...).scan()` |
| 推进 Baseline | `FileTracker.commit(message="...")` |
| 回滚一次提交 | `FileTracker.undo()` |
| 读 Baseline/工作区内容 | `FileTracker.read_baseline_content(path)` / `read_working_content(path)` |
| 函数级扫描 | `SymbolTracker(file_tracker, registry).scan_symbols()` |
| 注册解析器 | `ParserRegistry().register(".py", PythonASTParser())` |
| 函数级 Diff | `SymbolChange.diff()` |
| 序列化为 LLM 文本 | `SymbolChangeSet.to_llm_text()` |

---

## 5. 测试覆盖对照

本库已内置单元测试（共 27 项，`pytest` 全绿，`mypy` 零报错），与上述用例一一对应：

| 测试文件 | 覆盖要点 |
| --- | --- |
| `tests/filetracker/test_scanner.py` | 递归扫描、exclude 模式、Baseline 目录排除、元数据记录 |
| `tests/filetracker/test_baseline.py` | 原子写（`*.tmp`→`replace`）、崩溃不破坏 manifest、快照 push/pop |
| `tests/filetracker/test_tracker.py` | 扫描/提交/回滚、失败提交回滚、undo 快照、commit 元数据、diff 内容 |
| `tests/filetracker/test_cli.py` | CLI 子命令 scan/commit/undo/symbols、undo 无内容、compact 与 llm 格式、无变更提示 |
| `tests/symbol_tracker/test_python_parser.py` | 语法错误安全回退、签名解析、类/方法限定名、嵌套函数、body_hash |
| `tests/symbol_tracker/test_symbol_tracker.py` | 重命名=删除+新增、仅改体=MODIFIED、增删符号、无解析器跳过、to_llm_text |
