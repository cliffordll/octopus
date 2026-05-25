# Octopus Baseline Cleanup

## 1. 文档目标

本文档记录 Octopus 第一阶段 Step 1「仓库基础收敛」的执行结果。

目的不是重复 `CLAUDE.md` 或 `docs/FEATURE.md` 的规范说明，而是把这一步实际做了什么、为什么这样做、以及对照哪条规则做的，固化为可回溯的执行记录。

后续阶段如果对某项基础配置的取舍有疑问，应优先回到本文档查依据，而不是再次重新判断。

## 2. 执行范围

本次收敛只动以下四类对象：

- 顶层目录中与 Python 服务端兼容重写无关的残留文件
- `pyproject.toml` 中与 Octopus 目标无关的依赖
- `.gitignore` 中与旧栈相关的忽略规则
- 本地参考克隆 `upstream-reference/` 的处理方式

不在本次执行范围内的内容：

- `server/`、`packages/` 等业务目录骨架（属于 Step 2 及之后）
- 共享契约源文件，例如 `packages/shared/`、`packages/database/schema/`（A 主改）
- `docs/step-03/A-CONSTRAINTS.md`、`docs/step-04/SCHEMA-COMPATIBILITY.md`（A 已交付）

## 3. 执行依据

本次清理的判断标准来自：

- `CLAUDE.md` 的「清理原则」：保留与上游参考实现 Python 化改造直接相关的内容；删除 Node workspace、Tauri、旧项目协作文档、与兼容重写无关的历史文件
- `CLAUDE.md` 的「项目定位」与「核心约束」：Octopus 是上游控制面服务端的 Python 兼容替代实现，不是 CLI 工具、不是桌面应用、不是抓取系统
- `docs/DESIGN.md` 第 6.1 节：部署形态为多 server pod + 共享 PostgreSQL，无桌面打包诉求
- `docs/FEATURE.md` Step 1 验收标准：顶层配置不再混入明显无关的旧项目信息；基础依赖和忽略规则能解释为 Octopus 所需

## 4. 顶层目录现状

执行后顶层只保留以下条目：

```
.git/
.github/
docs/
upstream-reference/   本地参考克隆,已通过 .gitignore 忽略
.gitignore
.python-version
CLAUDE.md
pyproject.toml
```

变更：

- 删除 `package.json`：原内容为 Node workspace 声明（`workspaces: ["packages/*"]`），Python 服务端不需要 Node workspace 元数据
- `upstream-reference/`：保留作为本地对照源，不进仓库；`CLAUDE.md` 已明确「对照实现以上游参考仓库路径为准」，本目录只是为方便本地查阅

未来如果新增 `server/`、`packages/`、`tests/` 等目录，应按 `docs/DESIGN.md` 第 7 节的结构落地，不再次重复本步骤判断。

## 5. `pyproject.toml` 收敛

### 5.1 保留的运行依赖

| 依赖 | 用途 | 归属阶段 |
|---|---|---|
| `sqlalchemy[asyncio]>=2.0` | ORM 与 async 事务边界 | Step 4 数据库映射层 |
| `aiosqlite>=0.19` | 本地开发期 SQLite 驱动 | Step 4 |
| `httpx>=0.28` | 服务端调用 runtime / 外部 HTTP | Step 8 runtime orchestration |
| `psutil>=6.0` | lifespan 与后台任务的进程级观测预留 | Step 2 / Step 5 |
| `python-ulid>=2.0` | 上游参考实现风格 ID 生成 | Step 3 shared contract |
| `pyyaml>=6.0` | 配置文件解析 | Step 2 config |
| `jsonschema>=4.20` | shared validator | Step 3 shared contract |

### 5.2 保留的 dev 依赖

| 依赖 | 用途 |
|---|---|
| `ruff>=0.6` | 静态检查 |
| `pyright>=1.1.409` | 类型检查 |
| `pytest>=8.0` | 测试框架 |
| `pytest-asyncio>=0.23` | async 测试支持 |
| `types-pyyaml>=6.0` | PyYAML 类型存根 |

### 5.3 删除的依赖

| 依赖 | 删除原因 |
|---|---|
| `typer>=0.13` | CLI 框架,Octopus 是服务端项目,无 CLI 入口诉求 |
| `prompt_toolkit>=3.0` | 终端交互组件,与服务端无关 |
| `trafilatura>=1.6` | 网页正文抽取,与上游参考实现兼容重写无关 |
| `duckduckgo-search>=5.0` | 搜索客户端,与上游参考实现兼容重写无关 |
| `pyinstaller>=6.0` | 桌面/单文件打包,DESIGN.md 6.1 已说明部署形态为 pod,不需要打包 |

`[dependency-groups] build` 整组随 `pyinstaller` 一并删除。

### 5.4 暂不引入的依赖

| 依赖 | 暂不引入原因 |
|---|---|
| `asyncpg` 或其它 PG 驱动 | `DESIGN.md` 6.1 写明生产为 PostgreSQL,但 Step 1 不落数据库层。按「不投机加依赖」原则,留到 Step 4 真正落 schema 时再加 |

### 5.5 其它字段调整

- 删除 `authors = [{ name = "lianaipeng" }]`：来自旧项目的署名,与 Octopus 无关
- 删除 `readme = "README.md"`：当前仓库无 `README.md` 文件,保留该字段会形成悬空引用
- `description` 改为 `Octopus: Python compatibility rewrite of the upstream control-plane server`,与项目定位对齐

## 6. `.gitignore` 收敛

### 6.1 保留章节

- Python 字节码与编译产物
- 虚拟环境（`.venv/`、`venv/`、`env/`）
- 打包产物（`build/`、`dist/`、`*.egg-info/`）
- 测试与类型检查缓存（`.pytest_cache/`、`.pyright_cache/`、`.ruff_cache/`、`.coverage*`）
- SQLite 运行时文件（`*.db`、`*.sqlite` 等）
- IDE / 编辑器（`.vscode/`、`.idea/`、`*.swp`）
- OS 元文件（`.DS_Store`、`Thumbs.db`、`desktop.ini`）
- 密钥 / 本地配置（`.env`、`*.key`、`*.pem`、`secrets.json`）
- Claude Code 本地设置（`.claude/settings.local.json`、`.claude/shell-snapshots/`）
- 日志与杂项（`*.log`、`logs/`、`tmp/`）
- 本地草稿（`docs/others/`）

### 6.2 新增条目

- `upstream-reference/`：本地参考用的上游参考实现源码副本,不进仓库

### 6.3 删除章节

- Node / Bun（`node_modules/`、`.turbo/`、`.parcel-cache/`、`*.tsbuildinfo`）
- 前端构建输出（`.next/`、`out/`、`packages/app/dist/`）
- Tauri（`packages/desktop/tauri/target/`、`packages/desktop/tauri/gen/`、`packages/desktop/tauri/binaries/*.exe`、`target/`）
- PyInstaller（`*.spec.bak`）
- 旧运行时目录（`.chariot/`、`chariot-dev/`）

删除依据：以上章节涉及的目录在 Octopus 仓库中既不存在也不会出现,留着会让后续维护者误以为有相关产物。

## 7. `CLAUDE.md` 关键章节状态

本步骤不修改 `CLAUDE.md`,但需要确认以下章节已稳定,作为后续阶段执行的依据：

- 项目定位：明确为上游控制面服务端的 Python 兼容替代实现
- 核心约束：业务表 / API / 枚举 / 状态值不变,pod 编排与 organization 分配由外层系统负责
- 目录规范：与 `DESIGN.md` 第 7 节对齐
- 编码规范：要求内聚、封装、可扩展,不发明新产品概念
- 测试规范：契约兼容测试 + 工作流测试 + ownership 测试为主
- 提交流程：每次开发完先汇报,等待用户确认,仅在明确 `commit` 指令后提交
- 双人协作规范 + 双人合并规范：契约先合实现后合,B 不主改契约源文件
- 非目标 + 清理原则：明确本项目不做什么、清理时的判断依据

## 8. 验证方式

执行后做以下验证：

- `git status` 显示三处变更：`D package.json`、`M .gitignore`、`M pyproject.toml`
- `git check-ignore -v upstream-reference` 输出 `.gitignore:<line>:upstream-reference/`,确认本地参考目录已被忽略
- `uv tree` 能完整解析 `pyproject.toml`,所有保留依赖均成功 resolve
- 全仓 grep `trafilatura|prompt_toolkit|duckduckgo|typer|pyinstaller` 无任何源码引用,确认删除依赖不影响任何已有代码

## 9. 后续阶段衔接

- Step 2 服务端骨架在 `pyproject.toml` 基础上追加了 `fastapi` 与 `uvicorn[standard]` 运行依赖,以及 `[tool.hatch.build.targets.wheel] packages = ["server"]` 构建配置;具体追加理由见 `docs/step-02/SERVER-SKELETON.md` §6
- Step 4 数据库映射层落地时,按 `DESIGN.md` 6.1 增加 PostgreSQL 异步驱动,本文档不预先决定具体包名
- 任何新增运行依赖都应在引入时同步在对应阶段的操作文档中给出归属与用途,避免再次出现「依赖来源不明」的情况
- 本文档不再随后续阶段修改;如果未来对基础配置有进一步收敛,新建对应阶段的操作文档,不覆写本文
