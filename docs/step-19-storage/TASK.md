# Step 19: Attachment / Storage

状态：待开发

## 目标

将原 Step 22 提前到 Step 19，优先补齐 runtime/chat/workspace 产物需要的完整 storage lifecycle。这样后续 Observability 可以直接引用稳定的 attachment、asset 和 work product 存储对象，而不是先做临时日志字段再返工。

## 任务

- 实现 attachment contract、元数据持久化与业务关联。
- 建立 storage adapter 边界及本地开发实现。
- 实现上游范围内的上传、读取和关联行为。
- 承接 Step 18 的消息附件/产物引用，将引用能力升级为完整 storage lifecycle。
- 为 Step 20 Observability 预留稳定对象引用，避免 run/runtime/workspace 可见性只能返回本地临时路径。

## 边界

- Storage backend 不得改变对外 payload 结构。
- 不实现生产级 observability、run events 或 stdout/stderr 查询；这些顺延到 Step 20。
- 不实现 cost、budget、quota 或治理逻辑；这些顺延到 Step 21/22。

## 验收

- Tests 覆盖对象关联、内容缺失与 organization scope。
- Tests 覆盖 chat attachment 从 Step 18 metadata 升级到可上传/读取内容的生命周期。
- Tests 覆盖 runtime/workspace 产物引用不会跨 organization 泄漏。
