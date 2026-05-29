# Step 18: Chat Attachments 与基础运行可见性

状态：待开发

## 目标

在 Step 16 Chat/Messenger 可用后，补齐消息使用链路中最容易阻塞真实调试的附件引用、产物引用和基础运行可见性。

本步骤不是完整 Storage，也不是完整 Observability；它只补齐 Chat 使用 Agent 时必须能看到和引用的最小服务端信息。

Step 16 已经提供 `POST /api/chats/{id}/messages` 和 stream fallback，但当前 server 仍存在一个事务边界缺口：`add_message_and_reply` 在同一请求事务中先写用户消息再同步执行 runtime，runtime 失败会导致事务回滚，用户消息刷新后不可见。该问题会直接阻塞真实对话调试，因此必须作为本步骤首个任务收口。

## 任务

### 18A: Message persistence 与 runtime failure boundary

作用：保证用户已经发送并被 server 接收的消息不会因为 assistant/runtime 失败而丢失，避免 UI/CLI 刷新后看不到用户消息。

- 对照上游 `chat-assistant`、`chats` service 和 stream route，确认用户消息、assistant invocation 和失败状态的副作用时机。
- 调整 `add_message_and_reply` 或其调用边界，使用户消息先进入可提交的持久化状态，再执行 runtime。
- runtime 失败时保留用户消息，并返回或持久化可读失败摘要；不得把失败伪装成成功 assistant reply。
- stream route 中已经发送 `ack` 的 `userMessage` 必须最终能通过 `GET /api/chats/{id}/messages` 查询到。
- 增加 contract/workflow tests，覆盖非流式 runtime 失败、stream runtime 失败、消息列表刷新和 conversation `lastMessageAt` 行为。

### 18B: Chat attachment / artifact reference

作用：让消息可以引用已存在的附件、workspace work product、run result 或文件引用，为真实任务讨论提供上下文。

- 为 chat/message 增加上游兼容的附件或 artifact reference 字段与 response 形态。
- 允许消息关联 workspace work product、run result 或已存在的文件引用，不在本步骤实现完整对象存储。
- 在 conversation/message 查询中保留 organization scope，避免跨 organization 泄漏附件、产物或 run 信息。

### 18C: Chat execution visibility

作用：让 UI/CLI 能看到消息是否触发执行、执行是否失败、失败摘要是什么。

- 补齐 chat -> agent invocation -> run/runtime result 的基础可见性字段。
- 将 runtime error、timeout、cancel/interrupted 等基础结果归一成可读 response 字段。
- 保留与 Step 19 observability 的边界：本步骤只提供 Chat 使用所需的最小可见性，不实现生产级日志和指标。

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
