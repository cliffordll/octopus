# Step 9 A Constraints

## 当前状态

当前文件是草稿版本。

用途是先给出 Step 9 的 chat 方向，不作为当前阶段的冻结实现约束。等 B 完成前序控制面和 runtime 相关步骤后，再按真实阻塞点逐步细化。

## 目标

最后处理 chat 兼容实现，优先对齐会话、消息、上下文链接和 convert-to-issue 的核心能力。

## 本阶段范围

- `GET /api/chats`
- `POST /api/chats`
- `POST /api/chats/{chatId}/messages`
- `POST /api/chats/{chatId}/convert-to-issue`
- conversation、message、attachment、context link 的核心语义

## A 线必须先冻结的内容

- 以下内容暂不视为已冻结，只是后续收口方向：
- chat 核心对象字段
- 消息顺序和角色语义
- convert-to-issue 契约
- attachment / context link 的基础兼容边界

## B 线实现边界

- 先做最小可跑通会话链路
- 再补 message、attachment、context link 和 issue 转换
- 不在第一轮就追求全量历史能力

## 验收 demo

- Demo 1：创建最小 chat 会话并写入消息
- Demo 2：演示一次关键动作，例如 convert-to-issue
- Demo 3：对照 上游参考实现 展示消息顺序和字段结构
- Demo 4：展示 chat 契约测试或 workflow 测试结果

## 待确认项

- assistant / system / user 消息的最终归一化模型
- chat 与 issue / approval 之间的对象关联方式
- attachment 元数据与实际内容读取边界

## Step 3 完成后再补

- chat 第一批真正需要进入 shared contract 的类型边界
- message 顺序与分页语义
- convert-to-issue 的最小成功链路
- attachment / context link 的首批兼容字段

## 当前不冻结

- 全量 messenger / streaming 分支
- 大量历史消息恢复策略
- 全量 UI 交互细节
