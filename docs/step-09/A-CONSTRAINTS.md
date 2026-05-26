# Step 9 A Constraints

## 当前状态

当前文件是草稿版本。

用途是先给出协作与资源模块的边界，不在这一步提前冻结所有聊天对象和资源元数据。等运行、工作区和基础业务主线打稳后，再把 chat / attachment / artifact / storage / skill / plugin 的兼容细节逐项收紧。

## 目标

合并推进以下能力：

- 聊天与协作
- 附件与产物
- 对象存储
- skills / plugins / 智能体资源装配

## 本阶段范围

- `chats`
- `messages`
- `convert-to-issue`
- `chat_attachments`
- artifact / generated file
- storage adapters
- bundled skills
- plugins
- agent resource bindings

## A 线必须先冻结的内容

以下内容当前仍是草稿收口方向：

- chat 会话 / 消息 / context link 的最小语义
- attachment / artifact 的最小元数据边界
- storage adapter 的最小职责边界
- skill / plugin metadata 与扫描规则
- agent resource binding 的最小语义

同时，Step 9 继续承接来自历史 workflow notes 的审批管理约束，后续收紧时至少要覆盖：

- approval 第一批状态值：
  - `pending`
  - `approved`
  - `rejected`
  - `needs_revision`
- approval 创建默认状态：
  - `pending`
- approve / reject / request revision 的最小权限边界：
  - 只有 board 身份允许执行
- approve 后关联 blocked issue 的恢复规则：
  - 有 assignee 时恢复到 `in_progress`
  - 无 assignee 时恢复到 `todo`
- requester 为 agent 时，resubmit 只允许 requester 自己执行
- approval activity action 至少保留：
  - `approval.created`
  - `approval.approved`
  - `approval.rejected`
  - `approval.revision_requested`
  - `approval.resubmitted`
  - `approval.comment_added`
  - `issue.approval_linked`
  - `approval.linked_issue_assignee_wakeup_queued`
  - `approval.linked_issue_assignee_wakeup_failed`
  - `approval.requester_wakeup_queued`
  - `approval.requester_wakeup_failed`

## B 线实现边界

- chat、storage、skill / plugin 不得互相偷穿边界
- 先做最小真实链路，再补大量历史兼容细节
- storage 必须通过集中边界接入，不允许直接散写本地文件路径
- skill / plugin 资源发现与装配必须走集中 registry / scanner
- approval workflow 相关实现时，不得：
  - 修改上述 approval 状态值命名
  - 改写 blocked issue 恢复规则
  - 删除上述 approval activity action 名称
  - 删除 board 身份守卫条件

## 验收 demo

- Demo 1：演示最小 chat 会话、消息写入和 convert-to-issue
- Demo 2：演示 attachment / artifact 写入、读取或定位
- Demo 3：演示 skill / plugin 扫描、注册或装配路径
- Demo 4：展示 contract / workflow 测试结果

## 待确认项

- chat 消息顺序、分页与角色模型的最终口径
- attachment metadata 与内容读取是否同阶段冻结
- artifact 与 workspace / run 的交叉关系最小范围
- skill / plugin 是否需要区分启用态和可见态
- approval comment、request revision、resubmit 是否与审批管理一起冻结完整 payload 语义
- wakeup queued / failed activity 是否在同一步冻结 payload 字段

## Step 8 完成后再补

- chat 第一批 shared types 的字段级清单
- attachment / artifact / storage 的回归测试矩阵
- skill / plugin metadata 的最终字段边界
- agent resource binding 的最小 contract
- approval approve / reject / revision / resubmit 的字段级契约
- approval activity payload 的最小字段集

## 当前不冻结

- 全量 streaming / messenger 分支
- 大量历史消息恢复策略
- observability / failover / compatibility diff
- 全量 provider 资源差异
