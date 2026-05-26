# Step 4 Schema Upstream Align

## 1. 文档目标

本文档记录 Step 4 交付后对 `packages/database/schema/` 的一次性 upstream 对齐修复执行结果。

Step 4 第一版 schema 实现基于 `docs/step-04/SCHEMA-COMPATIBILITY.md` 当时的盘点产出。事后用 organizations 表对照 upstream Drizzle 源码做了一次完整 diff,发现盘点和实现都存在多处与 upstream 偏差,影响范围覆盖全部 6 张表。本文档把这一轮 alignment 的发现与修复固化下来,作为后续读 schema 源文件时的参考。

## 2. 触发原因

用户提出疑问:「B 是全部参考 upstream 仅进行语言重构,还是按文档实现?」用 organizations 表做了 demo 对照,发现:

- 上游两个索引是 `uniqueIndex`,A 文档没标记 unique,我建成普通 Index → 严重功能 bug
- 上游 `text` 列被我加了 `String(N)` 长度上限 → 拒绝合法长 url_key/name
- 上游 `jsonb` 列被我用了通用 `JSON` → 丢失 PG jsonb 性能
- 我多加了 `onupdate=func.now()` → 与 upstream 行为不一致

进一步对其余 5 张表 diff,确认同类问题贯穿所有表,并发现 A 的 SCHEMA-COMPATIBILITY 在 `issues` / `issue_comments` / `issue_approvals` / `activity_log` 等表的索引清单上大量遗漏。

## 3. 执行范围

本次只动以下内容:

- `packages/database/schema/{organizations,issues,approvals,issue_comments,issue_approvals,activity_log}.py` 6 张表全部按 upstream 对齐
- `docs/step-04/SCHEMA-COMPATIBILITY.md` 补齐字段级 PG 类型规则、updated_at 行为约定、各表完整索引清单与 unique 标记
- `docs/step-04/DATABASE-MAPPING.md` §5.6 更新 `issues_open_automation_execution_uq` 状态说明(从「延后」改为「已落地」)
- `tests/contract/test_step4_database.py` 调整 `test_issue_indexes_match_step4_scope` → `test_issue_indexes_match_upstream`,索引集合从 3 项扩到 13 项;为 `test_list_org_issues_filters_by_org` 的 2 个 organization seed 显式指定唯一 `issue_prefix`
- `tests/ownership/test_step5_ownership.py` `_seed_org_with_ownership` helper 给每个 organization 设唯一 `issue_prefix`(避免 unique 约束冲突)

不在本次范围:

- 任何 Step 5 ownership 表或 Step 6 read API 内容
- ORM 模型自身命名 / 类设计(只动列类型、索引、FK 级联)
- 上游 schema 之外的字段引入

## 4. 修复矩阵

### 4.1 字段类型

| 类别 | upstream Drizzle | Step 4 第一版 Python | 本次修复 |
|---|---|---|---|
| UUID 主键 / 外键 | `uuid` | `String(36)` | **保持 `String(36)`**(DATABASE-MAPPING §5.2 已声明的跨数据库决定,本次不变) |
| 用户标识 / 通用字符串 | `text` | `String(36)` / `String(64)` / `String(128)` / `String(255)` | 改为 `Text()`,移除所有长度上限 |
| JSON 列 | `jsonb` | `JSON` | 改为 `JSON().with_variant(JSONB(), "postgresql")` |
| 整数 / 布尔 / 时间 | `integer` / `boolean` / `timestamp(withTimezone:true)` | `int` / `Boolean` / `DateTime(timezone=True)` | 保持不变(已对齐) |

### 4.2 索引

按上游 Drizzle 源码对照,补齐 4 张表共 **19 个**先前未建的索引,并把 3 处 unique 标记落实:

| 表 | 第一版索引数 | upstream 索引数 | 新增 |
|---|---|---|---|
| `organizations` | 2(普通) | 2(都 unique) | 2 处补 `unique=True` |
| `issues` | 3 | 13 | 10 新增(含 1 个 unique 部分索引) |
| `approvals` | 1 | 1 | 已对齐 |
| `issue_comments` | 0 | 4 | 4 新增 |
| `issue_approvals` | PK | PK + 3 普通 | 3 新增 |
| `activity_log` | 0 | 3 | 3 新增 |

`issues_open_automation_execution_uq` 第一版 DATABASE-MAPPING §5.6 标记「延后到 Step 6/7」,本次直接落地。用 `Index(..., postgresql_where=..., sqlite_where=...)` 表达 WHERE 子句,SQLite 和 PG 都支持部分索引。

`issues_identifier_idx` 第一版建成普通索引,本次加 `unique=True`。

### 4.3 FK 级联

按 upstream 对照,补齐 `issue_approvals` 表 2 处 `ON DELETE CASCADE`:

- `issue_id → issues.id` ON DELETE CASCADE
- `approval_id → approvals.id` ON DELETE CASCADE

`linked_by_agent_id → agents.id` ON DELETE SET NULL 因 `agents` 表不在 Step 4 第一批,Python schema 暂不加 FK 约束(沿用 DATABASE-MAPPING §5.5「FK 目标不在本批就不加」)。

### 4.4 行为

`updated_at` 全表移除 `onupdate=func.now()`。与 upstream 一致,由应用层在 mutation 时显式设置时间戳。详见 SCHEMA-COMPATIBILITY §4.3。

## 5. 影响范围与修复策略

### 5.1 是否破坏 Step 4 / Step 5 已有功能

不破坏:

- Step 4 演示链路`OrgService.list() → list_organizations() → session` 仍工作
- Step 5 ownership guard 路径不依赖 schema 内部细节
- 现有 503 board guard 行为不变(`curl /api/orgs` 仍返回 HTTP 503)

测试需要小幅调整:

- `test_step4_database.py::test_issue_indexes_match_step4_scope` 重命名为 `test_issue_indexes_match_upstream`,索引集合从 3 项扩到 13 项
- `test_step4_database.py::test_list_org_issues_filters_by_org` 2 个 organization 显式给唯一 `issue_prefix`,避免 unique 约束冲突
- `test_step5_ownership.py::_seed_org_with_ownership` helper 每个 organization 设唯一 `issue_prefix`

### 5.2 是否需要 alembic 迁移

不需要,因为:

- Step 4 还没建立任何 PG 实际部署
- 现行测试只用 in-memory SQLite,每次 `Base.metadata.create_all` 都按最新 schema 重建
- 真正上 PG 时 alembic 迁移在 Step 5+ 或部署阶段统一引入,届时基于本次对齐后的 schema 生成第一份完整 baseline

## 6. 验证

按 `CLAUDE.md` 默认本地验证顺序:

- `ruff check . --fix`
- `ruff format .`
- `pytest`(55 个测试全过)
- `pyright`(0 errors)

启动 server 端到端:

- `uv run uvicorn server.app:app --host 127.0.0.1 --port 8000`
- `curl http://127.0.0.1:8000/api/orgs` → HTTP 503(Step 2 board guard 行为保留)

## 7. 经验与后续改进

### 7.1 经验

- 双人协作中 B 默认信任 A 文档,A 漏盘的字段级 / 索引级细节 B 不会自动发现
- 类型决定(`text` vs `varchar`, `jsonb` vs `json`, unique 标记)是契约的一部分,SCHEMA-COMPATIBILITY 必须显式表达
- 一次仔细的 upstream demo 能暴露贯穿全部 6 张表的同类问题,值得做

### 7.2 后续

- A 后续盘点新表时,SCHEMA-COMPATIBILITY 应明确每字段 PG 类型 + 每索引 unique 标记 + FK ondelete 行为,避免再依赖 B 事后对齐
- B 在 Step 6+ 接入新 schema 时,先扫一遍 upstream 源码做一次 quick diff 再实现,把 alignment 提前
- 后续阶段如发现类似 schema 漂移,在对应 step 目录下新增类似的 `*-UPSTREAM-ALIGN.md` 记录,避免修复结论散落

## 8. 不在本次解决

- UUID 列类型策略仍是 `String(36)`(详见 DATABASE-MAPPING §5.2)。如未来需要严格对齐 PG `uuid` 类型,可以加 `String(36).with_variant(UUID(as_uuid=False), "postgresql")`,本次保持现状以减少 PR 范围
- `agents` / `projects` / `goals` / `heartbeat_runs` / `project_workspaces` / `execution_workspaces` 等不在 Step 4 第一批的目标表 FK 仍不加约束。等对应表纳入后续 step schema 范围时按 upstream 补
