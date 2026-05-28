# Step 16: Chat / Messenger 扩展

状态：待开发

## 依赖边界

Step 11F 仅提前实现触发 Agent runtime 并保存响应所需的最小 conversation/message 链路。上游 chat assistant invocation 不持久化为 heartbeat run。本步骤负责剩余的完整 Chat / Messenger 服务端兼容范围，不重复定义或替换该执行入口。

## 任务

- 实现除 Step 11F 最小 Agent 对话闭环以外、纳入范围的 conversation/message contract、持久化和 API。
- 保持 organization scope 以及与既有业务对象的兼容关联。
- 实现未被 Step 11F 覆盖的上游服务端消息侧副作用。

## 不包含

- Attachment/storage 行为，归 Step 21；消息侧最小附件/产物引用入口如阻塞 Chat 验收，归 Step 17。
- 完整 cost/budget/quota/skills analytics 治理归 Step 19/20。

## 验收

- Tests 验证 payload、消息排序、scope 和支持的副作用。
