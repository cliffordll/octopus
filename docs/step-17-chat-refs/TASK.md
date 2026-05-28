# Step 17: Chat Attachments 与基础运行可见性

状态：待开发

## 目标

在 Step 16 Chat/Messenger 可用后，补齐消息使用链路中最容易阻塞真实调试的附件引用、产物引用和基础运行可见性。

本步骤不是完整 Storage，也不是完整 Observability；它只补齐 Chat 使用 Agent 时必须能看到和引用的最小服务端信息。

## 任务

- 为 chat/message 增加上游兼容的附件或 artifact reference 字段与 response 形态。
- 允许消息关联 workspace work product、run result 或已存在的文件引用，不在本步骤实现完整对象存储。
- 补齐 chat -> agent invocation -> run/runtime result 的基础可见性字段，使 UI/CLI 能展示消息是否触发执行、执行是否失败、失败摘要是什么。
- 在 conversation/message 查询中保留 organization scope，避免跨 organization 泄漏附件、产物或 run 信息。

## 边界

- 不实现完整上传、下载、对象存储 lifecycle；完整 Attachment / Storage 归 Step 21。
- 不实现生产级日志、指标、恢复矩阵；基础 Observability 归 Step 18，完整 Hardening 归 Step 23。
- 不新增上游不存在的附件业务模型；若上游只有引用关系，本步骤只实现引用关系。

## 验收

- Tests 覆盖消息携带附件/产物引用后的 payload、排序和 scope。
- Tests 覆盖消息触发 agent 后可以查询到基础 execution visibility。
- Tests 覆盖引用不存在、跨 organization 引用和已删除引用的错误行为。
