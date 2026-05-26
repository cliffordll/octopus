# Step 12 A Constraints

## 当前状态

当前文件是草稿版本。

用途是先给出聊天、附件、产物与对象存储模块的收口方向，不在这一步一次冻结所有协作对象历史细节。等运行与工作区主线打稳后，再把 chat / attachment / artifact / storage 的细节逐步收紧。

## 目标

整合以下协作与存储能力：

- chats / messages / convert-to-issue
- attachments / artifacts / generated files
- storage adapters

## 本阶段范围

- chat 会话与消息主链路
- convert-to-issue
- chat attachments
- artifact / generated file
- storage adapter 边界

## A 线必须先冻结的内容

- chat 会话 / 消息 / context link 最小语义
- convert-to-issue 最小成功链路
- attachment / artifact 的最小 metadata 边界
- storage 适配层的最小职责边界

## B 线实现边界

- chat 与 storage 仍按资源边界分层
- 先保证最小真实链路，再补大量历史兼容细节
- artifact 不得绕过集中 storage 层

## 验收 demo

- Demo 1：演示最小 chat 会话和消息写入
- Demo 2：演示 convert-to-issue
- Demo 3：演示 attachment / artifact 的写入与读取
- Demo 4：展示 contract / workflow 测试结果

## 待确认项

- chat message 顺序、分页与角色模型
- attachment metadata 与实际内容边界
- artifact 与 run / workspace 的关联最小范围

## 当前不冻结

- skills / plugins / agent resource
- observability / failover / compatibility diff
