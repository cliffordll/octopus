# Step 18: Chat Attachments 与基础运行可见性

状态：待开发

## 目标

在 Step 16 Chat/Messenger 可用后，补齐消息使用链路中最容易阻塞真实调试的附件引用、产物引用和基础运行可见性。

本步骤不是完整 Storage，也不是完整 Observability；它只补齐 Chat 使用 Agent 时必须能看到和引用的最小服务端信息。

Step 16 已经提供 `POST /api/chats/{id}/messages` 和 stream fallback，但当前 server 仍存在一个事务边界缺口：`add_message_and_reply` 在同一请求事务中先写用户消息再同步执行 runtime，runtime 失败会导致事务回滚，用户消息刷新后不可见。该问题会直接阻塞真实对话调试，因此必须作为本步骤首个任务收口。

## 上游与本地依据

开发前必须对照以下上游参考文件，确认 Chat message、assistant invocation、stream error 和 attachment/reference 语义：

- `D:\coding\rudder\server\src\routes\chats.ts`
- `D:\coding\rudder\server\src\routes\chats.stream-routes.ts`
- `D:\coding\rudder\server\src\services\chats.ts`
- `D:\coding\rudder\server\src\services\chat-assistant.ts`
- `D:\coding\rudder\packages\shared\src\types\chat.ts`
- `D:\coding\rudder\packages\db\src\schema\chat_messages.ts`

本地已有基础：

- `server/services/chats.py` 已实现 conversation/message service、runtime 调用、proposal 和 stream ack。
- `server/routes/chats.py` 已暴露 `POST /api/chats/{id}/messages` 与 `POST /api/chats/{id}/messages/stream`。
- `packages/database/schema/chats.py` 已有 `chat_messages.structured_payload`，可承载最小 execution visibility 或引用结构。
- `packages/database/schema/workspaces.py` 已有 `IssueWorkProduct`，Step 18 可以先引用既有 work product，不提前实现完整 storage。

## 任务

### 18A: Message persistence 与 runtime failure boundary

作用：保证用户已经发送并被 server 接收的消息不会因为 assistant/runtime 失败而丢失，避免 UI/CLI 刷新后看不到用户消息。

设计：

- 不把 chat assistant invocation 改成 heartbeat run。
- 将用户消息落库与 runtime 调用拆成可独立提交的边界，避免 runtime 异常回滚用户消息。
- runtime 失败时不创建成功 assistant message；错误通过 HTTP/stream error 和后续 visibility 字段表达。
- stream route 中已经发送 `ack` 的 `userMessage` 必须最终能通过 `GET /api/chats/{id}/messages` 查询到。

计划：

1. 在 `tests/contract/test_step18_chat_refs.py` 增加失败测试：非流式 runtime adapter 抛错或返回 error 后，用户消息仍可查询，conversation `lastMessageAt` 指向用户消息。
2. 增加 stream 失败测试：收到 `ack` 后 adapter 失败，stream 返回 error event，随后 message list 仍包含 ack 的 user message。
3. 修改 `server/services/chats.py`：把创建用户消息、touch conversation 和 runtime 执行拆成明确 helper；必要时在 route/service 层使用独立 session/transaction 或受控 commit，避免当前请求事务整体回滚。
4. 修改 `server/routes/chats.py`：保持既有错误码语义，确保非流式 runtime 失败仍返回可读 `detail`，stream 失败仍输出 error event。
5. 验证 Step 16 chat assistant/proposal 测试不回退。

### 18B: Chat attachment / artifact reference

作用：让消息可以引用已存在的附件、workspace work product、run result 或文件引用，为真实任务讨论提供上下文。

设计：

- 优先复用 `chat_messages.structured_payload` 承载最小引用结构；只有上游明确存在独立表时才新增 migration。
- 引用对象只允许指向已存在且同 organization 的资源，例如 `IssueWorkProduct`、heartbeat run result 或后续 storage attachment 元数据。
- 不在本阶段实现上传、下载、对象存储 body 或权限策略。

计划：

1. 对照上游确认 message attachment/reference 的字段名和 response shape。
2. 在 `packages/shared/types/chat.py` 增加最小 typed structure，保持字段可选，不破坏既有 message response。
3. 在 `packages/shared/validators/chat.py` 扩展 `validate_add_chat_message`，允许携带确认过的引用 payload。
4. 在 `server/services/chats.py` 写入 message `structured_payload` 前校验引用归属，同 organization 才允许保存。
5. 在 `tests/contract/test_step18_chat_refs.py` 覆盖 work product/run reference 的成功、缺失和跨 organization 拒绝。

### 18C: Chat execution visibility

作用：让 UI/CLI 能看到消息是否触发执行、执行是否失败、失败摘要是什么。

设计：

- visibility 信息挂在 chat message 或 conversation response 中，用于说明本次 chat 是否触发 runtime、使用哪个 agent/runtime、失败摘要是什么。
- 不提前实现完整 observability store；stdout/stderr 深度日志、指标和恢复矩阵归 Step 19/24。
- 对外字段必须可由上游 chat 类型或服务行为解释；如上游仅提供 error text，本地不得扩展成新的复杂状态机。

计划：

1. 对照上游确认 chat assistant result/error 在 message 或 response 中的字段表达。
2. 在 shared type 中增加最小 execution visibility 字段，优先作为 `structuredPayload` 的规范子结构。
3. 在 runtime success/failed/timeout/cancel 分支写入可读摘要。
4. 在 message list/detail 中返回该结构，保持旧字段兼容。
5. 增加 contract tests 覆盖成功、失败和无 runtime 三种可见性。

## 边界

- 不实现完整上传、下载、对象存储 lifecycle；完整 Attachment / Storage 归 Step 22。
- 不实现生产级日志、指标、恢复矩阵；基础 Observability 归 Step 19，完整 Hardening 归 Step 24。
- 不新增上游不存在的附件业务模型；若上游只有引用关系，本步骤只实现引用关系。
- 不把 chat assistant invocation 伪装成 heartbeat run；若上游没有持久化 run，本步骤只补齐 message/runtime visibility。
- 不通过 UI optimistic state 代替 server 持久化修复；UI 只能展示临时状态，server 必须保证已接收用户消息可刷新查询。

## 验收

- Tests 覆盖 runtime 失败后用户消息仍被持久化，刷新消息列表可见。
- Tests 覆盖 stream ack 后 runtime 失败，ack 的 user message 仍可查询，错误事件可读。
- Tests 覆盖消息携带附件/产物引用后的 payload、排序和 scope。
- Tests 覆盖消息触发 agent 后可以查询到基础 execution visibility。
- Tests 覆盖引用不存在、跨 organization 引用和已删除引用的错误行为。

建议验证命令：

```powershell
$env:UV_CACHE_DIR='D:\tmp\octopus-uv-cache-verify'
uv run pytest tests/contract/test_step18_chat_refs.py -q
uv run pytest tests/contract/test_step16_chat_assistant_routes.py tests/contract/test_step16_chat_stream_routes.py -q
uv run ruff check packages/shared/types/chat.py packages/shared/validators/chat.py server/routes/chats.py server/services/chats.py tests/contract/test_step18_chat_refs.py
uv run ruff format --check packages/shared/types/chat.py packages/shared/validators/chat.py server/routes/chats.py server/services/chats.py tests/contract/test_step18_chat_refs.py
uv run pyright packages/shared server tests/contract/test_step18_chat_refs.py
```
