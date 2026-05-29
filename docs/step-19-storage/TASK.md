# Step 19: Attachment / Storage

状态：已完成

## 目标

将原 Step 22 提前到 Step 19，优先补齐 runtime/chat/workspace 产物需要的完整 storage lifecycle。这样后续 Observability 可以直接引用稳定的 attachment、asset 和 work product 存储对象，而不是先做临时日志字段再返工。

## 任务

- 实现 attachment contract、元数据持久化与业务关联。
- 建立 storage adapter 边界及本地开发实现。
- 实现上游范围内的上传、读取和关联行为。
- 承接 Step 18 的消息附件/产物引用，将引用能力升级为完整 storage lifecycle。
- 为 Step 20 Observability 预留稳定对象引用，避免 run/runtime/workspace 可见性只能返回本地临时路径。

## 上游证据

开发前必须对照以下上游文件，不得自定义新的 storage/attachment 模型：

- `D:\coding\rudder\server\src\storage\types.ts`
- `D:\coding\rudder\server\src\storage\service.ts`
- `D:\coding\rudder\server\src\storage\local-disk-provider.ts`
- `D:\coding\rudder\server\src\routes\assets.ts`
- `D:\coding\rudder\server\src\routes\chats.ts`
- `D:\coding\rudder\server\src\routes\issues.ts`
- `D:\coding\rudder\server\src\services\assets.ts`
- `D:\coding\rudder\packages\db\src\schema\assets.ts`
- `D:\coding\rudder\packages\db\src\schema\chat_attachments.ts`
- `D:\coding\rudder\packages\db\src\schema\issue_attachments.ts`
- `D:\coding\rudder\packages\shared\src\types\asset.ts`
- `D:\coding\rudder\packages\shared\src\types\chat.ts`
- `D:\coding\rudder\packages\shared\src\types\issue.ts`

## 本地现状

- Step 18 已新增 `assets` 与 `chat_attachments` 表、`ChatAttachment` 类型、`POST /api/orgs/{orgId}/chats/{chatId}/attachments` metadata route。
- Step 18 目前只保存 asset metadata，不写入对象内容；`contentPath` 指向 `/api/assets/{assetId}/content`，但本地尚未实现 asset content route。
- Step 15 已有 `IssueWorkProduct` 与 runtime `work_products` 持久化，但 work product 目前只引用外部/本地路径，不具备统一 storage object lifecycle。
- 本地尚未实现 `issue_attachments`、通用 storage provider/service、multipart upload、content download 和 delete lifecycle。

## 执行计划

### 19A: Storage provider 与 asset content 基线

状态：已完成

作用：建立上游式 `StorageService` 抽象和本地磁盘 provider，让 server 能写入、读取、head、delete 受 organization scope 约束的对象。

修改范围：

- 新增 `server/storage/types.py`：定义 `StoredObject`、`PutFileResult`、`StorageProvider`、`StorageService`。
- 新增 `server/storage/local_disk.py`：实现本地磁盘对象写入/读取/head/delete，拒绝绝对路径、空 key、`.`、`..`。
- 新增 `server/storage/service.py`：实现 object key 生成、sha256、org prefix 校验、provider 包装。
- 新增 `server/storage/__init__.py`：暴露 `get_storage_service()`，默认 base dir 为 `.octopus/storage`，可通过 `OCTOPUS_STORAGE_DIR` 覆盖。
- 新增 `packages/database/queries/assets.py`：提供 asset create/get/delete 基础查询。
- 新增/补齐 `packages/shared/types/asset.py` 与 `packages/shared/api_paths/assets.py`。
- 新增 `server/routes/assets.py`：实现 `GET /api/assets/{assetId}/content`，按 asset org scope 校验后返回内容。
- 修改 `server/routes/__init__.py`：注册 assets route。
- 新增 `tests/contract/test_step19_storage.py`：覆盖 storage path guard、put/get/head/delete、asset content route、跨 org 拒绝。

验收：

- `GET /api/assets/{assetId}/content` 能读取 Step 18 已记录 asset 的真实对象内容。
- object key 必须以 `{orgId}/` 开头，跨 organization 读取拒绝。
- 本地磁盘 provider 不允许路径逃逸。

### 19B: Chat attachment multipart upload

状态：已完成

作用：把 Step 18 的 chat attachment metadata route 升级为完整上传入口，同时保留 metadata-only 兼容能力。

修改范围：

- 修改 `server/routes/chats.py`：`POST /api/orgs/{orgId}/chats/{chatId}/attachments` 支持 multipart `file` 上传；JSON metadata route 保持兼容。
- 修改 `server/services/chats.py`：新增通过已创建 asset 创建 attachment 的 service 分支，避免 route 直接写业务表。
- 修改 `packages/shared/types/chat.py` / validators：确保 response shape 不变，`contentPath` 仍为 `/api/assets/{assetId}/content`。
- 新增/扩展 `tests/contract/test_step19_storage.py`：覆盖 chat upload、message hydration、content download、空文件/非法 content type/跨 conversation 拒绝。

验收：

- 上传 chat attachment 后，message list 返回 attachment，`contentPath` 可下载原始内容。
- JSON metadata 创建仍可用，用于外部对象已存在的兼容场景。
- 文件内容不存入数据库，只存 storage backend。

### 19C: Issue attachment upload 与读取

状态：已完成

作用：补齐上游控制面常用的 issue attachment API，使 agent/CLI 能把截图、报告、图片等文件挂到 issue/comment 上。

修改范围：

- 新增 `IssueAttachment` schema 和 migration，字段对齐上游核心表：`org_id`、`issue_id`、`issue_comment_id`、`asset_id`、`usage`、timestamps。
- 新增 query/service：创建、列表、删除 issue attachment，复用 `assets` 与 `StorageService`。
- 新增 shared type/path/validator：`IssueAttachment`、`POST /api/orgs/{orgId}/issues/{issueId}/attachments`、`GET /api/issues/{issueId}/attachments`、`DELETE /api/attachments/{attachmentId}`。
- 修改 `server/routes/issues.py`：增加 issue attachment upload/list/delete。
- 新增/扩展 `tests/contract/test_step19_storage.py`：覆盖 issue attachment lifecycle、comment attachment usage、content download、delete 后内容不可读、跨 org 拒绝。

验收：

- issue attachment 可上传、列出、下载、删除。
- 删除 attachment 应删除业务关联，并删除未被其他 attachment 引用的 storage object。
- issue/comment scope 必须属于同一 organization。

### 19D: Runtime/workspace work product storage reference

状态：已完成

作用：让 runtime 产物可以引用稳定 storage object，为 Step 20 Observability 复用。

修改范围：

- 修改 `packages/shared/types/workspace.py`：为 `IssueWorkProduct` 明确 `assetId`/`contentPath` 或 metadata reference 的兼容字段，保持已有字段不破坏。
- 修改 `server/services/workspaces.py`：当 runtime `work_products` 包含可存储内容或本地文件路径时，通过 storage service 创建 asset，再把 asset/contentPath 写入 work product metadata。
- 修改 `server/services/heartbeat.py`：调用 workspace persistence 时传入 storage service 或 storage context。
- 新增/扩展 `tests/contract/test_step19_storage.py` 和 Step 15 相关回归：覆盖 runtime work product -> asset -> contentPath 查询。

验收：

- runtime work product 有稳定 content reference，不再只暴露临时本地路径。
- 不改变 runtime adapter 执行协议；adapter 继续输出 `work_products` 原始证据，server 负责归档。
- 对不能读取或不应归档的外部链接，只保留原引用，不伪造 asset。

## 边界

- Storage backend 不得改变对外 payload 结构。
- 不实现生产级 observability、run events 或 stdout/stderr 查询；这些顺延到 Step 20。
- 不实现 cost、budget、quota 或治理逻辑；这些顺延到 Step 21/22。
- 本阶段默认实现 `local_disk` provider；S3 配置和 provider 可保留接口边界，实际生产接入可后续补。
- 不处理 UI/CLI 上传体验，只保证 server API contract 可用。
- 不把 organization resources 的文本 catalog 自动搬进 storage；project resource attachment 已属于 Step 10/15。

## 验收

- Tests 覆盖对象关联、内容缺失与 organization scope。
- Tests 覆盖 chat attachment 从 Step 18 metadata 升级到可上传/读取内容的生命周期。
- Tests 覆盖 runtime/workspace 产物引用不会跨 organization 泄漏。

## 实现记录

- 19A 已建立 `StorageService` / `local_disk` provider、asset 查询与 `GET /api/assets/{assetId}/content`。
- 19B 已支持 chat attachment multipart 文件上传，同时保留 JSON metadata-only 兼容入口。
- 19C 已支持 issue attachment 上传、列表、删除和 content 下载，并新增 `issue_attachments` migration。
- 19D 已支持 runtime/workspace work product `content` 归档为 asset，并返回 `assetId` / `contentPath`。
- multipart 解析依赖 `python-multipart`，已写入 `pyproject.toml` 与 `uv.lock`。

## 验证命令

每个子任务至少运行：

```powershell
$env:UV_CACHE_DIR='D:\tmp\octopus-uv-cache-verify'
uv run pytest tests/contract/test_step19_storage.py -q
uv run pytest tests/contract/test_step18_chat_refs.py -q
uv run ruff format --check server/storage server/routes/assets.py server/routes/chats.py server/routes/issues.py server/services/chats.py server/services/workspaces.py packages/database/queries/assets.py tests/contract/test_step19_storage.py
uv run ruff check server/storage server/routes/assets.py server/routes/chats.py server/routes/issues.py server/services/chats.py server/services/workspaces.py packages/database/queries/assets.py tests/contract/test_step19_storage.py
uv run pyright server packages tests/contract/test_step19_storage.py
```
