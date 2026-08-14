# JARVIS 架构实现计划（微内核 + 一切皆插件）

> **For Hermes:** 用 subagent-driven-development 按任务逐条实现。本文件是架构契约，实现者严格照此落地。

**Goal:** 从零写一个 Python 微内核 AI 助手「贾维斯」，LLM provider、记忆后端、对话通道（Telegram/终端/Web）、配置**全部是插件**，每个插件是独立 git 仓库，内核统一 `clone/pull` 并 `importlib` 加载，**所有插件支持热重启**（git HEAD 或配置 mtime 变化 → teardown + reload，不重启进程）。环境锁在项目内 `.venv`，本机零污染。编译/测试交给 GitHub Actions。

**Architecture:** 极简内核只做四件事：① 插件生命周期管理（clone/pull/load/hot-reload）② 把插件注册的工具聚合成一个工具表 ③ 跑 agent 循环（LLM 流式 + tool_call 路由回插件）④ 通道适配（把外部输入喂给 agent、把输出送回去）。所有「能力」都是插件：provider 插件给内核一个 `chat()` 函数，memory 插件给 `load()/append()`，channel 插件给 `listen()/send()`，config 插件给 `get()/watch()`。

**Tech Stack:** Python 3.11+，`uv`（环境+依赖）、`click`（CLI）、`httpx`（LLM/HTTP）、`pydantic`（插件 manifest 校验）、`gitpython` 或 subprocess git。云端验证：GitHub Actions `setup-python` + `uv`。

**Hard Constraints（不可违反）:**
- 项目只在 `~/Desktop/jarvis/`，与 `~/Desktop/GQY` 零交集；不读不改 GQY 任何文件、不碰 `macos/GQYApp`、不进系统 PATH 覆盖旧 `gqy`。
- 本地工作只写代码 + `git commit` + `git push`；不本地跑重依赖安装/全套测试，交给 Actions。
- 数据目录默认 `~/Library/Application Support/jarvis`，与 GQY 的 `gqy` 目录无关。

---

## 0. 目录布局（最终形态）

```
~/Desktop/jarvis/
├── .venv/                      # 项目私有环境（uv 创建，activate 即用，本机零污染）
├── pyproject.toml              # 仅内核瘦依赖
├── README.md                   # 贾维斯简介（非 GQY）
├── uv.lock
├── jarvis/
│   ├── __init__.py
│   ├── main.py                 # 入口：子命令 bootstrap / chat / telegram
│   ├── kernel.py               # 微内核：装配插件、跑 agent 循环、工具路由
│   ├── plugin.py               # PluginManager：clone/pull/importlib/hot-reload
│   ├── types.py                # 跨插件契约类型（ToolSpec / ChatRequest / 等）
│   ├── config.py               # 内核配置加载（指向 config 插件的桥）
│   └── plugins.toml            # 插件注册表（name + git + enabled + ref）
├── plugins/                    # 已拉取的插件（各是独立 git 子仓库）
│   ├── provider-openai/        # 插件：LLM provider（独立仓库）
│   ├── memory-jsonl/           # 插件：记忆后端（独立仓库）
│   ├── channel-telegram/       # 插件：Telegram 通道（独立仓库）
│   ├── channel-terminal/       # 插件：终端通道（独立仓库）
│   └── config-core/            # 插件：配置即插件（独立仓库，持有 config.toml）
└── .github/workflows/ci.yml    # 云端：setup-python + uv sync + pytest
```

> 关键：插件目录 `plugins/*` 各自是 **git 仓库**（不是子模块，由 PluginManager 直接 `git clone`/`pull` 管理，便于独立版本与热重启）。

---

## 1. 插件契约（一切皆插件的「宪法」）

### 1.1 Manifest：`plugins/<name>/plugin.toml`
每个插件根目录一个 `plugin.toml`，内核校验后加载：
```toml
[plugin]
name = "provider-openai"
kind = "provider"          # provider | memory | channel | config | tool
version = "0.1.0"
entry = "plugin.py"        # 入口模块
hot_reload = true          # 是否允许热重启（默认 true）
dependencies = []         # 该插件自带依赖（内核用 venv 装）
[provides]
tools = []                 # 该插件额外暴露的工具名（provider/memory 可为空）
```

### 1.2 生命周期接口（`plugin.py` 必须实现）
```python
from jarvis.types import ToolSpec, ChatRequest, ChatStream, KernelApi

def setup(kernel: KernelApi) -> None:
    """注册本插件提供的工具 / 服务。仅在加载或热重启时调用一次。"""
    ...

def teardown(kernel: KernelApi) -> None:
    """释放资源（关连接、停后台任务）。热重启前必调用。"""
    ...

# 以下按 kind 提供对应钩子（非必须全部）：
# provider:  def chat(req: ChatRequest) -> ChatStream
# memory:    def load(session) -> list;  def append(session, msg) -> None
# channel:   def listen(cb) -> None;     def send(recipient, text) -> None
# config:    def get(key) -> Any;        def watch(cb) -> None
```

### 1.3 工具注册（tool 类或任何插件可暴露工具）
```python
@kernel.tool("hass.light_on")
def light_on(room: str, brightness: int = 100) -> str:
    """打开指定房间的灯。"""
    ...
```
内核把所有插件的 `@kernel.tool` 收集成一张 `name -> callable` 表，LLM 的 `tool_call` 按 `name` 路由过去。**热重启时整表重建**（先 `teardown` 全部再重新 `setup`）。

---

## 2. 热重启机制（全插件支持）

**触发器（内核后台 watcher 线程 / asyncio task）：**
1. `git -C plugins/<name> rev-parse HEAD` 与上次的 HEAD 不同 → 该插件上游更新了。
2. 插件配置 mtime / config 插件发出 `watch` 变更事件 → 配置变了。

**热重启流程（不重启进程）：**
```
detect change
  → kernel.unload(plugin): call plugin.teardown(); 从工具表移除其工具
  → if git change: git pull --ff-only (失败则跳过本次重载，保留旧版)
  → importlib.reload(module) or 重新 import 子模块
  → plugin.setup(kernel): 重新注册工具/服务
  → 在跑的对话不受影响（agent 循环每次拿当前工具表快照）
```
**隔离保证：** agent 循环每轮对话开始 `snapshot = kernel.tools_snapshot()`，执行期间用这个快照，热重启改的是「下一轮」的表，绝不半路改表导致正在跑的 tool_call 崩。

---

## 3. 各插件职责（v1 最小集）

### 3.1 插件存放形式（v1 决策：普通子目录，不独立建 git 仓库）
- **v1：插件就是 `~/Desktop/jarvis/plugins/<name>/` 下的普通子目录**，不 `git submodule`、不单独 `gh repo create`、不各自配证书/鉴权。避免多仓库鉴权复杂度（YAGNI）。
- 内核扫 `plugins/` 下每个子目录 → 读 `plugin.toml` → `importlib` 加载 → 聚合工具表 → 热重启靠**文件 mtime / 内容变更**触发（不靠 git pull）。
- **先要验证的核心命题**：「任意目录都能成为贾维斯的插件」——注册机制成立、工具自动出现、热重启生效。
- **后置（机制跑通后再定）**：某些插件升级为「独立 git 仓库 + 自动 `git pull`」。彼时只是把"目录"换成"可被 clone/pull 的目录"，PluginManager 加一个可选的 remote+ref 字段即可，架构不变。

### 3.2 v1 插件清单
| 插件 | kind | 暴露 | 热重启 |
|---|---|---|---|
| `provider-echo`（**内置桩，非真实 LLM**） | provider | `chat()` 回显 + 可触发测试工具 | ✅ |
| `memory-jsonl` | memory | `load()/append()`，会话历史落 JSONL | ✅ |
| `channel-terminal` | channel | 终端 REPL 输入/输出 | ✅ |
| `config-core` | config | 读 `config.toml`，`watch()` | ✅ |

> **LLM provider 插件化能力保留，但 v1 不实现具体 provider（`provider-openai` 等暂缓）。** 先用 `provider-echo` 桩把「对话→工具路由→记忆→输出」整条链路跑通，不依赖真实模型、不处理 base_url/key。等插件机制稳了，再单独做真实 `provider-*` 插件挂上（届时 arichtecture 不变，只是多一个目录）。
> **Telegram / Home Assistant 同为后置**（机制验证完再各做一个插件目录），理由相同：先证明"目录即插件"，再扩展具体通道与工具。

---

## 4. 分步任务（每条 2–5 分钟，TDD）

### Task 1: 仓库与 venv 初始化
- 创建 `~/Desktop/jarvis/` + `git init` + `pyproject.toml`（内核依赖：`click httpx pydantic gitpython`）。
- `uv venv && uv pip install -e .`（本地仅装内核瘦依赖，插件依赖按需装）。
- 写 `.github/workflows/ci.yml`：`setup-python 3.11` + `uv` + `uv sync` + `pytest`。
- 测：`uv run pytest` 空测试通过（Actions 也绿）。提交。

### Task 2: 插件契约类型 `jarvis/types.py`
- 定义 `ToolSpec`、`ChatRequest`、`ChatStream`、`KernelApi`（含 `tool()` 装饰器、`register_service()`）。
- TDD：写 `tests/test_types.py` 测 `KernelApi.tool` 注册/快照。

### Task 3: PluginManager `jarvis/plugin.py`
- `load(plugins.toml)`：对每个条目 `git clone`（无则）→ `git pull --ff-only` → `importlib` 加载 `entry` → `setup(kernel)`。
- 后台 watcher：git HEAD / 配置 mtime 变化触发 `unload→pull→reload`。
- TDD：`tests/test_plugin.py` 用本地 fixtures 仓库模拟 clone/pull/热重载。

### Task 4: 内核装配 `jarvis/kernel.py`
- 启动：加载 `config-core` → 暴露 `kernel.config` → 加载 provider/memory/channel/tool 插件 → 聚合工具表。
- `run_agent(session, user_msg)`：memory.load → 调 provider.chat（带工具表 schema）→ 流式输出 → 遇 tool_call 路由到插件 callable → 结果回灌 → 结束 append 到 memory。
- TDD：mock provider+memory，验证 tool_call 路由与记忆写入。

### Task 5: 入口 `jarvis/main.py`
- 子命令：`bootstrap`（首次 clone 全部插件）、`chat`（终端通道）、`telegram`（telegram 通道）。
- TDD：CLI 解析测试。

### Task 6: 最小插件集（v1：普通子目录，非独立 git 仓库）
- `provider-echo`（桩）、`memory-jsonl`、`channel-terminal`、`config-core`，各放 `plugins/<name>/` 普通目录。
- 每个含 `plugin.toml` + `plugin.py` + 自己的测试。
- **验证核心命题**：内核扫 `plugins/` 自动注册、工具表聚合、改文件 mtime 触发热重启。

### Task 7（后置，机制跑通后再做）: 真实 provider 插件
- 做 `provider-openai`（或你的兼容端点）作为 `kind=provider` 插件挂上，替换 `provider-echo` 桩。
- 届时仅多一个 `plugins/` 子目录，架构不变。

### Task 8（后置）: 示例通道/工具插件（Telegram、Home Assistant）
- 各自作为 `plugins/<name>/` 普通目录插件：`channel-telegram`（`getUpdates` 长轮询 + `allowed_users` 白名单）、`tool-homeassistant`（`hass.light_on`/`hass.status`）。
- 验证：加一个插件目录 → 内核自动出现对应能力，无需改内核。

### Task 9: 文档与 README
- `README.md` 写贾维斯定位、一切皆插件理念、如何写/挂载一个插件、如何接 Home Assistant。

---

## 5. 验证（端到端，云端优先）
- CI：每次 push 跑 `pytest`（内核 + 各插件单测 + 热重启模拟）。
- 手动冒烟（本地仅 `uv run`，不装重依赖）：`uv run jarvis chat` 能对话；`uv run jarvis telegram` 手机发消息能回；改一个插件仓库 push → 内核热重载该插件新工具。

## 6. 风险 / 取舍
- **插件依赖冲突**：每个插件声明 `dependencies`，内核用统一 venv 装；若冲突，后续可改每插件独立 venv/子进程（架构不变）。
- **`git pull --ff-only` 失败**：保留旧版、记日志、不阻断，下一轮再试。
- **热重启竞态**：工具表用「每轮快照」隔离子，已在 §2 解决。
- **YAGNI**：v1 不做 Web 通道、不做插件市场 UI、不做权限沙箱（后续按需加）。
