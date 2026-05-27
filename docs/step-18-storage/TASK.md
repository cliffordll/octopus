# Step 18: Attachment / Storage

状态：待开发

## 任务

- 实现 attachment contract、元数据持久化与业务关联。
- 建立 storage adapter 边界及本地开发实现。
- 实现上游范围内的上传、读取和关联行为。

## 边界

- Storage backend 不得改变对外 payload 结构。

## 验收

- Tests 覆盖对象关联、内容缺失与 organization scope。
