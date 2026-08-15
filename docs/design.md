# FileTracker & SymbolTracker 模块设计与开发指导文档

## 1. 文档概述

### 1.1 背景与目标

为了解决在代码变更触发系统文档自动更新（LLM Pipeline）场景下，文件级 Diff 导致的 **Token 浪费** 与 **上下文不精确** 问题，本设计在底层物理文件追踪器（`FileTracker`）的基础上，通过分层组合架构引入了**函数/符号粒度**的变动感知能力（`SymbolTracker`）。

本文档作为**技术设计与开发指导规范**，旨在指导研发人员完成 `filetracker` 核心库及 `symbol_tracker` 组合模块的工程落地。

### 1.2 设计原则

1. **分层解耦 (Separation of Concerns)**：`FileTracker` 专注于物理文件级的状态变动与 Baseline 事务；`SymbolTracker` 专注于代码节点的 AST/语法切片与变动提取。两者严格分离。
2. **零运行时依赖 (Zero Third-Party Dependency)**：`filetracker` 核心标准库及 Python 语法解析器仅依赖 Python 3.10+ 标准库。
3. **延迟加载与按需解析 (Lazy Processing)**：扫描阶段优先通过文件元数据与 Hash 过滤，仅对物理变动的文件按需提取符号，降低 CPU 与内存开销。
4. **事务原子性 (Transactional Integrity)**：采用 **Scan $\rightarrow$ Extract $\rightarrow$ Process $\rightarrow$ Commit** 工作流，确保下游（LLM 文档更新）失败时 Baseline 绝对不推进。

---

## 2. 总体架构设计

### 2.1 分层架构图

```text
┌─────────────────────────────────────────────────────────────┐
│                 LLM Document Generator                      │
│     (应用层：消费 SymbolChangeSet，生成文档，调度 Commit)         │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                       symbol_tracker                        │
│ ┌──────────────────────┐        ┌─────────────────────────┐ │
│ │    SymbolTracker     │───────►│     ParserRegistry      │ │
│ └──────────┬───────────┘        └────────────┬────────────┘ │
│            │                                 │              │
│            │                              （派生）           │
│            │                                 ▼              │
│            │                    ┌─────────────────────────┐ │
│            │                    │   SymbolParser (接口)   │ │
│            │                    └────────────┬────────────┘ │
│            │                                 │              │
│            │                       ┌─────────┴─────────┐    │
│            │                       ▼                   ▼    │
│            │              ┌─────────────────┐ ┌───────────┐ │
│            │              │ PythonASTParser │ │  ... Parser│ │
│            │              └─────────────────┘ └───────────┘ │
└────────────┼────────────────────────────────────────────────┘
             │ 组合调用
             ▼
┌─────────────────────────────────────────────────────────────┐
│                        filetracker                          │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │                       FileTracker                       │ │
│ └──────────────┬───────────────────────────┬──────────────┘ │
│                ▼                           ▼                │
│       ┌─────────────────┐         ┌─────────────────┐       │
│       │ FileScanner/Diff│         │ BaselineManager │       │
│       └─────────────────┘         └─────────────────┘       │
└─────────────────────────────────────────────────────────────┘

```

---

## 3. 推荐工程目录结构

推荐的项目包目录组织如下：

```text
filetracker_project/
├── pyproject.toml
├── README.md
│
├── src/
│   ├── filetracker/                  # 底层文件追踪核心库
│   │   ├── __init__.py
│   │   ├── models.py                 # FileState, FileChange, ChangeSet 等
│   │   ├── scanner.py                # 递归文件扫描器
│   │   ├── diff.py                   # Unified Diff 与 二进制判断
│   │   ├── baseline.py               # Manifest 读写, Undo 恢复, 原子更新
│   │   ├── tracker.py                # FileTracker 主入口 API
│   │   └── cli.py                    # argparse CLI 封装
│   │
│   └── symbol_tracker/               # 上层函数粒度扩展库
│       ├── __init__.py
│       ├── models.py                 # SymbolState, SymbolChange, SymbolChangeSet
│       ├── base_parser.py            # SymbolParser 抽象基类
│       ├── registry.py               # ParserRegistry 注册表
│       ├── parsers/                  # 多语言解析策略包
│       │   ├── __init__.py
│       │   └── python_parser.py      # Python (ast 模块实现)
│       └── tracker.py                # SymbolTracker 主入口 API
│
└── tests/
    ├── filetracker/
    │   ├── test_scanner.py
    │   ├── test_baseline.py
    │   └── test_tracker.py
    └── symbol_tracker/
        ├── test_python_parser.py
        └── test_symbol_tracker.py

```

---

## 4. 核心模块与接口详细设计

### 4.1 数据模型设计 (`models.py`)

#### 4.1.1 底层文件模型 (`filetracker/models.py`)

```python
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from filetracker.tracker import FileTracker


class ChangeStatus(Enum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"


@dataclass(frozen=True)
class FileState:
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
        """延迟加载 Baseline 文本内容"""
        ...

    def new_content(self) -> str | None:
        """延迟加载 Working Dir 文本内容"""
        ...

    def diff(self) -> str:
        """生成文本 Unified Diff"""
        ...


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

```

#### 4.1.2 符号级模型 (`symbol_tracker/models.py`)

```python
from dataclasses import dataclass
from enum import Enum


class SymbolType(Enum):
    FUNCTION = "function"
    METHOD = "method"
    CLASS = "class"


@dataclass(frozen=True)
class SymbolState:
    name: str  # 完整限定名，如 "UserService.login" 或 "process_data"
    symbol_type: SymbolType
    signature: str  # 函数定义签名
    content: str  # 函数体完整源码
    body_hash: str  # 函数体 SHA-256 哈希
    start_line: int  # 起始行号
    end_line: int  # 结束行号


@dataclass
class SymbolChange:
    file_path: str
    symbol_name: str
    status: ChangeStatus  # ADDED / MODIFIED / DELETED
    old_symbol: SymbolState | None
    new_symbol: SymbolState | None

    def diff(self) -> str:
        """生成函数体级别的 Unified Diff"""
        ...


@dataclass
class SymbolChangeSet:
    added: list[SymbolChange]
    modified: list[SymbolChange]
    deleted: list[SymbolChange]

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.modified or self.deleted)

    def to_llm_text(self) -> str:
        """格式化为适合 LLM Prompt 消费的结构化 Markdown/Text"""
        ...

```

---

### 4.2 语法解析策略设计 (`symbol_tracker/base_parser.py` & `parsers/`)

#### 4.2.1 抽象基类 (`base_parser.py`)

```python
import abc
import hashlib
from symbol_tracker.models import SymbolState


class SymbolParser(abc.ABC):

    @abc.abstractmethod
    def parse(self, code_text: str) -> list[SymbolState]:
        """解析源码文本，提取符号列表。解析失败或为空时返回 []"""
        pass

    @staticmethod
    def compute_hash(text: str) -> str:
        return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()

```

#### 4.2.2 Python 解析器实现 (`parsers/python_parser.py`)

```python
import ast
from symbol_tracker.base_parser import SymbolParser
from symbol_tracker.models import SymbolState, SymbolType


class PythonASTParser(SymbolParser):

    def parse(self, code_text: str) -> list[SymbolState]:
        if not code_text or not code_text.strip():
            return []

        try:
            tree = ast.parse(code_text)
        except SyntaxError:
            # 遇到不合法的 Python 代码，安全回退
            return []

        lines = code_text.splitlines()
        symbols: list[SymbolState] = []

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                start = node.lineno - 1
                end = getattr(node, "end_lineno", start + 1)
                func_code = "\n".join(lines[start:end])

                # 提取简易函数签名
                args = [a.arg for a in node.args.args]
                sig = f"def {node.name}({', '.join(args)})"

                symbols.append(
                    SymbolState(
                        name=node.name,
                        symbol_type=SymbolType.FUNCTION,
                        signature=sig,
                        content=func_code,
                        body_hash=self.compute_hash(func_code),
                        start_line=node.lineno,
                        end_line=end,
                    )
                )
        return symbols

```

---

### 4.3 解析器注册表 (`symbol_tracker/registry.py`)

```python
from symbol_tracker.base_parser import SymbolParser


class ParserRegistry:

    def __init__(self):
        self._parsers: dict[str, SymbolParser] = {}

    def register(self, ext: str, parser: SymbolParser) -> None:
        """注册文件扩展名（例如 '.py'）与解析器的对应关系"""
        normalized_ext = (
            ext.lower() if ext.startswith(".") else f".{ext.lower()}"
        )
        self._parsers[normalized_ext] = parser

    def get_parser(self, file_path: str) -> SymbolParser | None:
        ext = (
            "." + file_path.rsplit(".", 1)[-1].lower()
            if "." in file_path
            else ""
        )
        return self._parsers.get(ext)

```

---

### 4.4 符号级追踪器实现 (`symbol_tracker/tracker.py`)

```python
from filetracker.models import ChangeStatus
from filetracker.tracker import FileTracker
from symbol_tracker.models import SymbolChange, SymbolChangeSet, SymbolState
from symbol_tracker.registry import ParserRegistry


class SymbolTracker:

    def __init__(
        self, file_tracker: FileTracker, registry: ParserRegistry | None = None
    ):
        self.file_tracker = file_tracker
        self.registry = registry or ParserRegistry()

    def scan_symbols(self) -> SymbolChangeSet:
        # 1. 触发物理文件级扫描
        file_changes = self.file_tracker.scan()

        added_symbols: list[SymbolChange] = []
        modified_symbols: list[SymbolChange] = []
        deleted_symbols: list[SymbolChange] = []

        for change in file_changes:
            parser = self.registry.get_parser(change.path)
            if not parser:
                # 若无对应的语法解析器，跳过该文件的符号级解析
                continue

            old_map = self._extract_symbol_map(parser, change.old_content())
            new_map = self._extract_symbol_map(parser, change.new_content())

            # 2. 对比新增与修改的函数
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

            # 3. 对比删除的函数
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
        self, parser, content: str | None
    ) -> dict[str, SymbolState]:
        if not content:
            return {}
        symbols = parser.parse(content)
        return {s.name: s for s in symbols}

```

---

## 5. 业务集成指导与事务闭环范例

应用层（LLM 文档更新工程）必须遵循以下标准工作流：

```python
from filetracker import FileTracker
from symbol_tracker import ParserRegistry, SymbolTracker
from symbol_tracker.parsers.python_parser import PythonASTParser

# Step 1: 初始化底层文件追踪器
file_tracker = FileTracker(
    root="./src", exclude=["*.pyc", "__pycache__", ".git"]
)

# Step 2: 配置符号解析器注册表
registry = ParserRegistry()
registry.register(".py", PythonASTParser())

# Step 3: 初始化符号追踪器
symbol_tracker = SymbolTracker(file_tracker, registry)

# Step 4: 扫描符号级差异
symbol_changes = symbol_tracker.scan_symbols()

if not symbol_changes.has_changes:
    print("No function-level changes detected. Skip processing.")
else:
    # Step 5: 构建 LLM 优化后的 Prompt
    prompt_context = symbol_changes.to_llm_text()

    # Step 6: 执行下游 LLM 处理逻辑
    try:
        success = call_llm_to_update_docs(prompt_context)
        if success:
            # Step 7: 下游成功，推进 Baseline
            file_tracker.commit(message="Docs updated for changed functions")
            print("Successfully updated docs and advanced baseline.")
        else:
            print(
                "LLM generation failed validation. Baseline NOT advanced. Retry available."
            )
    except Exception as e:
        # 处理异常，确保 Baseline 不推进
        print(f"Error during processing: {e}. Baseline remains unchanged.")

```

---

## 6. 质量保证与测试规范

开发人员在交付代码时，必须完成以下模块单元测试：

| 测试模块 | 关键测试用例 | 预期行为 |
| --- | --- | --- |
| **`filetracker/baseline.py`** | `test_atomic_manifest_update` | 模拟写入崩溃，验证 `.tmp` 机制确保 `manifest.json` 无坏块。 |
| **`filetracker/tracker.py`** | `test_failed_commit_rollback` | `commit()` 抛出异常时，`.filetracker/baseline/` 恢复原样。 |
| **`filetracker/tracker.py`** | `test_undo_snapshot` | 执行两次 `commit` 后调 `undo()`，验证 Baseline 回滚且不污染工作区源码。 |
| **`symbol_tracker/parsers`** | `test_python_syntax_error` | 源码存在语法错误时，`parse()` 返回 `[]` 且不崩溃。 |
| **`symbol_tracker/tracker`** | `test_function_rename` | 重命名函数时，精准识别为旧函数 `DELETED` + 新函数 `ADDED`。 |
| **`symbol_tracker/tracker`** | `test_function_body_modified` | 仅改动函数内部逻辑，精准识别为 `MODIFIED` 且 Body Hash 变更。 |