# Step 16: Chat / Messenger 扩展

状态：待开发

## 依赖边界

Step 11F 仅提前实现触发 Agent runtime 并保存响应所需的最小 conversation/message 链路。上游 chat assistant invocation 不持久化为 heartbeat run。本步骤负责剩余的完整 Chat / Messenger 服务端兼容范围，不重复定义或替换该执行入口。

## 任务

- 实现除 Step 11F 最小 Agent 对话闭环以外、纳入范围的 conversation/message contract、持久化和 API。
- 保持 organization scope 以及与既有业务对象的兼容关联。
- 实现未被 Step 11F 覆盖的上游服务端消息侧副作用。

## 上游证据

开发前必须对照以下上游文件，不能凭本地偏好重定义 Chat / Messenger 模型：

- `D:\coding\rudder\packages\db\src\schema\chat_conversations.ts`
- `D:\coding\rudder\packages\db\src\schema\chat_messages.ts`
- `D:\coding\rudder\packages\db\src\schema\chat_context_links.ts`
- `D:\coding\rudder\packages\db\src\schema\chat_conversation_user_states.ts`
- `D:\coding\rudder\packages\db\src\schema\messenger_thread_user_states.ts`
- `D:\coding\rudder\packages\shared\src\types\chat.ts`
- `D:\coding\rudder\packages\shared\src\types\messenger.ts`
- `D:\coding\rudder\packages\shared\src\validators\chat.ts`
- `D:\coding\rudder\server\src\routes\chats.ts`
- `D:\coding\rudder\server\src\routes\chats.stream-routes.ts`
- `D:\coding\rudder\server\src\routes\messenger.ts`
- `D:\coding\rudder\server\src\services\chats.ts`
- `D:\coding\rudder\server\src\services\chat-assistant.ts`
- `D:\coding\rudder\server\src\services\messenger.ts`
- `D:\coding\rudder\server\src\__tests__\chat-routes.test.ts`
- `D:\coding\rudder\server\src\__tests__\chat-assistant.test.ts`
- `D:\coding\rudder\server\src\__tests__\messenger-service.test.ts`

## 开发计划

### 16A: Chat contract、schema 与基础 CRUD

作用：先把上游 Chat Conversation / Message 的缺口补齐，稳定后续 assistant、context、messenger 的共同数据边界。

修改范围：

- `packages/shared/constants/`：补齐 chat conversation status、issue creation mode、message role/kind/status、context entity type。
- `packages/shared/types/`：补齐 `ChatConversation`、`ChatMessage`、`ChatContextLink`、`ChatRuntimeDescriptor` 等 response shape。
- `packages/shared/validators/`：补齐 create/update conversation、add message、conversation user state validator。
- `packages/database/schema/chats.py`：核对并补齐 `chat_conversations`、`chat_messages` 已有字段。
- `packages/database/schema/`：新增或补齐 `chat_conversation_user_states`。
- `packages/database/queries/chats.py`：补齐 conversation list/detail/update、messages list/create/update、user state。
- `server/services/chats.py`：补齐 conversation CRUD、message CRUD、unread/pinned/read state、latest reply preview。
- `server/routes/chats.py`：覆盖：
  - `GET /api/orgs/{orgId}/chats`
  - `POST /api/orgs/{orgId}/chats`
  - `GET /api/chats/{id}`
  - `PATCH /api/chats/{id}`
  - `GET /api/chats/{id}/messages`
  - `PATCH /api/chats/{id}/user-state`
- `tests/contract/test_step16_chat_routes.py`：覆盖 payload、status filter、q 搜索、scope guard、user state。
- `tests/workflows/test_step16_chat_workflow.py`：覆盖创建、更新、消息排序、unread/pinned/read state。

验收：

- conversation 可按 org 列表、创建、详情、更新。
- message 按 `createdAt` 正序返回，保留 `chatTurnId`、`turnVariant`、`supersededAt` 结构边界。
- board 本地 actor 和后续真实 actor 使用同一 user state 结构。

### 16B: Context links 与业务对象联动

作用：让 Chat 可以关联 issue、project、agent 等控制面对象，并在创建、查询、更新时保持 organization scope。

修改范围：

- `packages/database/schema/`：新增或补齐 `chat_context_links`。
- `packages/database/queries/chats.py`：新增 context link create/list/delete/upsert 查询。
- `server/services/chats.py`：实现 context link 校验、hydration 和 response entity summary。
- `server/routes/chats.py`：在 create/update/detail/list 中处理 `contextLinks`。
- `server/services/activity.py` 或既有 activity 写入点：记录 `chat.created`、`chat.context_linked`、`chat.updated`。
- `tests/contract/test_step16_chat_context_routes.py`：覆盖 context link payload 与跨 organization 拒绝。
- `tests/workflows/test_step16_chat_context_workflow.py`：覆盖 issue/project/agent link、重复 link 幂等、详情 hydration。

验收：

- context link 只允许同 organization 的 issue/project/agent。
- conversation response 中包含 `contextLinks` 和可展示的 linked entity summary。
- 创建或修改 context link 产生兼容 activity。

### 16C: Assistant reply 非流式闭环深化

作用：在 Step 11F 最小对话触发基础上，补齐上游 assistant message kind、proposal、ask_user、edit/regenerate 等消息侧语义；不把 chat assistant invocation 伪装为 heartbeat run。

修改范围：

- `server/services/chat_assistant.py`：对齐上游 assistant availability、runtime invocation、reply kind 映射。
- `server/services/chats.py`：实现 user message edit/regenerate 的 `supersededAt`、`chatTurnId`、`turnVariant` 行为。
- `server/routes/chats.py`：补齐 `POST /api/chats/{id}/messages` 的非流式 assistant reply。
- `server/services/approvals.py` 或 chat service 内部 proposal helper：创建 `chat_issue_creation`、`chat_operation` approval。
- `tests/contract/test_step16_chat_assistant_routes.py`：覆盖 unavailable、generation conflict、reply kind、proposal payload。
- `tests/workflows/test_step16_chat_assistant_workflow.py`：覆盖普通回复、ask_user、issue proposal、operation proposal、edit/regenerate。

验收：

- 同一 conversation 同时只能有一个 active generation。
- assistant message 支持 `message`、`ask_user`、`issue_proposal`、`operation_proposal`、`system_event`。
- proposal message 能正确关联 approval。
- chat assistant invocation 不创建 heartbeat run；它只在 message/approval/activity 侧产生上游证实的副作用。

### 16D: Chat issue conversion 与 operation proposal decision

作用：补齐 Chat 中将 proposal 落地为 issue 或操作决策的服务端入口，使 Chat 能从讨论推进到可追踪业务对象。

修改范围：

- `packages/shared/validators/`：补齐 `convertChatToIssue`、`resolveChatOperationProposal`。
- `server/routes/chats.py`：覆盖：
  - `POST /api/chats/{id}/convert-to-issue`
  - `POST /api/chats/{id}/operation-proposals/{messageId}/resolve`
  - 如上游存在 project context 入口，同步实现 `setChatProjectContext`。
- `server/services/chats.py`：实现 proposal extraction、issue 创建、operation proposal state 更新。
- `server/services/issues.py`：复用既有 issue 创建逻辑，不新增 chat 专用 issue 模型。
- `tests/contract/test_step16_chat_proposal_routes.py`：覆盖 conversion、decision action、非法 proposal。
- `tests/workflows/test_step16_chat_proposal_workflow.py`：覆盖 proposal -> approval -> issue / operation decision 全流程。

验收：

- conversion 使用现有 issue service 和 organization scope。
- 带 assignee/reviewer 的 proposal 必须走任务分配权限边界。
- operation proposal decision 更新 message structured payload 中的 state，并记录 activity。

### 16E: Messenger threads 与 read state

作用：补齐 Messenger 聚合入口，让 Chat、Issues、Approvals 等线程能在统一收件箱中展示、标记已读和计算关注状态。

修改范围：

- `packages/shared/constants/`：补齐 messenger thread kind、system thread kind。
- `packages/shared/types/`：补齐 `MessengerThreadSummary`、`MessengerThreadDetail`、thread item 类型。
- `packages/database/schema/`：新增或补齐 `messenger_thread_user_states`。
- `packages/database/queries/messenger.py`：新增 thread user state query。
- `server/services/messenger.py`：实现 chat/issues/approvals/system thread summary/detail 聚合。
- `server/routes/messenger.py`：覆盖：
  - `GET /api/orgs/{orgId}/messenger/threads`
  - `GET /api/orgs/{orgId}/messenger/chat/{conversationId}`
  - `POST /api/orgs/{orgId}/messenger/threads/{threadKey}/read`
  - `GET /api/orgs/{orgId}/messenger/issues`
  - `GET /api/orgs/{orgId}/messenger/approvals`
  - `GET /api/orgs/{orgId}/messenger/system/{threadKind}`
- `tests/contract/test_step16_messenger_routes.py`：覆盖 route shape、read state、not found。
- `tests/workflows/test_step16_messenger_workflow.py`：覆盖 thread summary、unread、needsAttention、chat detail。

验收：

- messenger thread key 与上游一致，例如 `chat:{conversationId}`、`issues`、`approvals`、system kind。
- read state 按 board user 维度保存。
- Messenger 不重新定义 chat 数据，只聚合已有 conversation/message/activity/approval/issue。

### 16F: Stream route 兼容占位与阶段边界

作用：上游存在 chat stream routes，但本阶段只在不阻塞主线的范围内实现稳定接口；复杂 transcript/observability/attachments 深化分别留给 Step 17/18。

修改范围：

- `server/routes/chats.py` 或独立 `server/routes/chats_stream.py`：对齐上游 stream route 路径和错误结构。
- `packages/shared/types/`：保留 `ChatStreamEvent`、transcript entry 类型。
- `server/services/chats.py`：支持 mark interrupted/stopped streaming message 的最小持久化行为。
- `tests/contract/test_step16_chat_stream_routes.py`：覆盖 stream route 可用性、generation conflict、assistant unavailable、interrupted message 标记。

验收：

- 如果实现完整流式输出，必须返回上游兼容事件：`ack`、`assistant_delta`、`assistant_state`、`transcript_entry`、`final`、`error`。
- 如果本阶段不实现完整 streaming，必须返回明确的兼容错误或稳定 fallback，不能破坏非流式消息闭环。
- transcript 深度展示、stdout/stderr 调试可见性归 Step 18。

## 执行顺序

1. 先执行 16A，提交 Chat contract、schema、基础 CRUD。
2. 执行 16B，提交 context links 与业务对象联动。
3. 执行 16C，提交 assistant reply 非流式闭环深化。
4. 执行 16D，提交 proposal conversion / decision。
5. 执行 16E，提交 Messenger threads 与 read state。
6. 执行 16F，提交 stream route 兼容占位或最小实现。

每一段完成后先停下说明“做了什么、作用是什么、验证结果是什么”，再按用户确认进入下一段。

## 不包含

- Attachment/storage 行为，归 Step 21；消息侧最小附件/产物引用入口如阻塞 Chat 验收，归 Step 17。
- 完整 cost/budget/quota/skills analytics 治理归 Step 19/20。

## 验收

- Tests 验证 payload、消息排序、scope 和支持的副作用。

## 验证命令

每个子任务至少运行：

```powershell
uv run ruff format --check .
uv run ruff check .
uv run pyright .
```

对应子任务还需运行新增或受影响测试，例如：

```powershell
uv run pytest tests/contract/test_step16_chat_routes.py -q
uv run pytest tests/workflows/test_step16_chat_workflow.py -q
uv run pytest tests/contract/test_step16_chat_context_routes.py -q
uv run pytest tests/workflows/test_step16_chat_context_workflow.py -q
uv run pytest tests/contract/test_step16_chat_assistant_routes.py -q
uv run pytest tests/workflows/test_step16_chat_assistant_workflow.py -q
uv run pytest tests/contract/test_step16_messenger_routes.py -q
uv run pytest tests/workflows/test_step16_messenger_workflow.py -q
```
