# Octopus Server Skeleton

## 1. 文档目标

本文档记录 Phase 2 Step 2「服务端骨架落地」的执行结果。

目的不是复述 `docs/DESIGN.md` 第 7.2 节的设计意图,而是把这一步实际建出来的 `server/` 文件结构、新增的运行依赖、最小启动链路以及为后续阶段预留的扩展点固化为可回溯的执行记录。

后续阶段如果要追问「app / config / lifespan / routes / services 当前为什么是这样」,先回到本文档查依据。

## 2. 执行范围

本次落地只动以下内容：

- 新增 `server/` 目录及其子模块的最小骨架
- 在 `pyproject.toml` 追加 `fastapi` 与 `uvicorn[standard]` 两条运行依赖
- 配置 `[tool.hatch.build.targets.wheel] packages = ["server"]`,让 `uv sync` 能把 `server` 注册为可导入包
- 修正 `pyproject.toml` description 中的上游项目名残留,与新版 `CLAUDE.md`「项目内禁止出现上游项目名」对齐

不在本次执行范围内的内容：

- `packages/shared/`(归 Phase 3,A 主导)
- `packages/database/`(归 Phase 4,A 主导 schema 边界)
- `ownership` 校验链路(归 Phase 5)
- 真实业务返回结构(当前最小验证入口只返回空数组,等 Step 3/4 落地后再补)

## 3. 执行依据

- `docs/FEATURE.md` Step 2 输出清单与验收 demo 要求
- `docs/DESIGN.md` 7.2 节 server 详细结构(`app.py` / `config.py` / `lifespan.py` / `routes/` / `services/` 职责划分)
- `docs/DESIGN.md` 第 4 节认可使用 FastAPI 替代上游参考实现的 Express
- `CLAUDE.md` 编码规范关于 route / service 职责边界、内聚、封装、可扩展的要求
- `CLAUDE.md` 关于「项目内禁止出现上游项目名」「不发明新接口前缀」「不发明新产品概念」的约束

## 4. 文件结构

```
server/
  __init__.py            空,使 server 成为顶层包(hatchling wheel 入口)
  src/
    __init__.py          空,使 server.src 成为子包
    app.py               FastAPI 应用工厂 + 模块级 app 单例
    config.py            Settings dataclass + 环境变量加载
    lifespan.py          async startup/shutdown context manager
    routes/
      __init__.py        register_routes(app),集中挂载所有子路由
      orgs.py            GET /api/orgs 路由,通过 Depends 注入 service
    services/
      __init__.py        空
      orgs.py            OrgService 占位实现,list() 当前返回 []
```

## 5. 各文件职责

### 5.1 `server/src/app.py`

应用入口。提供 `create_app()` 工厂函数,负责：

- 加载 `Settings`
- 创建 `FastAPI` 实例并挂载 `lifespan`
- 把 `settings` 挂到 `app.state`,后续模块按 `request.app.state.settings` 读取
- 调用 `register_routes(app)` 集中注册路由

模块级保留 `app = create_app()` 供 `uvicorn server.src.app:app` 直接引用。

### 5.2 `server/src/config.py`

配置层。当前实现：

- `Settings` 用 `@dataclass(frozen=True)` 表达只读语义
- `Settings.from_env()` 读取 `OCTOPUS_HOST` / `OCTOPUS_PORT` / `OCTOPUS_LOG_LEVEL`,提供本地默认值
- 暴露 `load_settings()` 顶层入口给 `app.py` 调用

刻意不引入 `pydantic-settings` 或自定义配置框架,保持依赖最小。后续阶段如果出现数据库连接、ownership 编号、外层代理上下文等配置项,按字段追加到 `Settings`,框架不必换。

### 5.3 `server/src/lifespan.py`

生命周期入口。当前主体是空 `yield`,但保留以下职责定位：

- Step 4 接入数据库连接池时在 yield 之前 init、之后 close
- Step 5 启动 ownership 续约任务在此挂载
- Step 7+ 启停 background 任务在此挂载

不允许把后台任务启动逻辑塞回 `app.py` 主入口。

### 5.4 `server/src/routes/`

路由层。当前实现：

- `__init__.py` 提供 `register_routes(app)`,集中调用 `app.include_router(...)`。后续新增资源面路由(`issues.py` / `chats.py` / `approvals.py` 等)只需在这里追加 import 与 include
- `orgs.py` 只承担路由注册、依赖注入、响应组装,不承载任何业务流程
- 当前依赖注入方式使用 FastAPI 原生 `Depends`,在 `get_org_service()` 工厂里返回 `OrgService()`。这是占位实现,A 在 Phase 3 冻结共享依赖注入边界后可以替换为统一 provider

### 5.5 `server/src/services/`

服务层。当前实现：

- `OrgService.list()` 返回 `[]`,作为最小启动验证占位
- 不引入任何业务语义、状态机、事务边界(那些归 Phase 5+)
- 按 `docs/DESIGN.md` 7.2.5 的要求按领域对象拆文件,后续 `issues.py` / `approvals.py` / `chats.py` 等在同层追加

## 6. 新增依赖与构建配置

### 6.1 运行依赖

| 依赖 | 用途 |
|---|---|
| `fastapi>=0.115` | Web 框架,`docs/DESIGN.md` 第 4 节明确认可 |
| `uvicorn[standard]>=0.32` | ASGI 服务器,`standard` extra 带 `httptools` / `uvloop` / `watchfiles` / `websockets`,与未来 chat 阶段的 streaming 需求方向一致 |

### 6.2 构建配置

```
[tool.hatch.build.targets.wheel]
packages = ["server"]
```

不加这一条,hatchling 默认按 project name `octopus` 查找同名目录,会因找不到而构建失败,导致 `uv sync` 无法把项目以 editable 形式安装。当前只声明 `server`,等 Phase 3/4 落地 `packages/shared/` 与 `packages/database/` 时再决定是否把它们纳入同一构建配置(也可以走 uv workspace 路线,届时再判)。

### 6.3 description 修正

把 `description` 中残留的上游项目名替换为 `"Octopus: Python compatibility rewrite of the upstream control-plane server"`,与新版 `CLAUDE.md`「项目内禁止出现上游项目名」对齐。

## 7. 启动验证

### 7.1 启动命令

```
uv run uvicorn server.src.app:app --host 127.0.0.1 --port 8000
```

启动日志：

```
INFO:     Started server process [...]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

### 7.2 最小验证调用

```
curl http://127.0.0.1:8000/api/orgs
```

返回：

```
[]
```

HTTP 状态码 `200`。服务端日志记录：

```
INFO:     127.0.0.1:... - "GET /api/orgs HTTP/1.1" 200 OK
```

### 7.3 为什么选 `/api/orgs` 而不是新发明的健康检查接口

- `CLAUDE.md` 与 `docs/DESIGN.md` 第 10.4 节要求不发明上游不存在的新接口前缀
- `docs/FEATURE.md` Step 2 接口示例就是 `/api/orgs` 与 `/api/issues`
- `docs/01-phase/API-COMPATIBILITY.md` 已经把 `/api/orgs` 列入第一批共享契约范围
- 返回空数组在响应 shape 上不违反任何已盘契约,等 Phase 4/6 落地后由真实查询替换

## 8. 与后续阶段的衔接预留

| 后续阶段 | 在本骨架的接入位 |
|---|---|
| Phase 3 shared contract | route 与 service 都直接引用 `packages/shared/` 的 API path、枚举、请求响应模型,替换当前模块内的临时返回类型 |
| Phase 4 database | `lifespan.py` 加 engine init / dispose;`OrgService` 通过 query 层访问数据库,替换占位 `[]` |
| Phase 5 ownership | route 与 service 之间引入 ownership 校验中间层;`background/` 子目录在 `lifespan` 里启动 |
| Phase 7 mutation workflow | `services/orgs.py` 等扩展为完整控制面语义层;`activity` 副作用与事务边界一并在此承载 |
| Phase 8 runtime orchestration | service 调用 `packages/runtimes/` 提供的统一 contract |

所有衔接点都落在既定边界内,不需要回头重写 `app.py` / `config.py` / `lifespan.py`。

## 9. 当前阶段不做的内容

- 不引入认证 / 鉴权中间件(归外层系统,本项目不实现完整 auth)
- 不引入 request id / trace 中间件(归 Phase 5 ownership 阶段或 observability 单独推进)
- 不引入 CORS / GZip 等装饰性中间件(等真实前端联调出现需求再加)
- 不引入 `packages/shared/` 引用(避免抢 A 的 Phase 3 边界)
- 不引入数据库会话(避免抢 A 的 Phase 4 schema 边界)
- 不引入测试套件(`tests/contract/` 等目录归 Phase 3 之后,跟随契约落地一起建)

## 10. 验证方式

- `uv sync` 能完整解析 `pyproject.toml`,fastapi / uvicorn 与现有依赖均成功 resolve
- `uv run uvicorn server.src.app:app --host 127.0.0.1 --port 8000` 启动后,uvicorn 日志显示 application startup complete
- `curl http://127.0.0.1:8000/api/orgs` 返回 `[]`,HTTP `200`
- 全仓 grep 上游项目名残留,确认本次新增的代码 / 文档 / 配置均未引入上游项目名字面值
