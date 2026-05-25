# Phase 2 Workflow Notes

## 目标

本文件用于支持 B 在 Phase 2 之后实现 `issue` / `approval` 的 mutation 与 workflow。这里只记录当前实现必须保持兼容的流转规则、守卫条件和 activity 副作用，不提前扩展 chat、runtime 或完整审计体系。

## 范围

- `issue` 创建、更新、删除、checkout、release、commit
- `approval` 创建、approve、reject、request revision、resubmit、comment
- 与上述操作直接相关的状态流转
- 与上述操作直接相关的 activity action

## Issue 状态流转

当前第一批实现至少按以下状态语义对齐 Rudder：

- `todo`
- `in_progress`
- `in_review`
- `blocked`
- `done`

### Reviewer decision 到 issue status 的映射

当 reviewer 记录 review decision 时，状态映射保持与 Rudder 一致：

- `approve` -> `done`
- `request_changes` -> `in_progress`
- `blocked` -> `blocked`
- `needs_followup` -> 不直接改 issue status

### 允许 reviewer decision 的前置状态

只有以下状态允许记录 reviewer decision：

- `in_review`
- `blocked`

如果当前 issue 不在上述状态，mutation 必须拒绝。

### 完成 issue 的权限约束

- reviewer agent 可以在 reviewable 状态下完成 issue
- assignee 只有在 `in_progress` 时才能直接完成 issue
- 如果 issue 存在 reviewer，且 assignee agent 尝试直接标记完成，状态不能直接落到 `done`，而应归一到 `in_review`

### reopen 约束

- 如果 issue 已关闭，并且更新时携带 `comment` 且显式要求 reopen
- 在未显式指定新 `status` 的情况下，默认重新打开到 `todo`

## Issue mutation 守卫条件

### Create

- 如果 actor 是 agent，且请求没有显式 assignee，默认将 issue 指派给当前 actor

### Update

- 变更 `assignee` 或 `reviewer` 时必须走权限检查
- 提交 `reviewDecision` 时必须同时提交 `comment`
- actor 无权完成 issue 时，不能把状态写成 `done`

### Checkout

- project 处于 paused 状态时，checkout 必须拒绝
- agent 只能以自己的 agent 身份 checkout，不能替其他 agent checkout

### Commit

- `commit` 只允许 agent 身份执行
- 返回体需要保持 Rudder 的 report 结构

## Issue activity action

当前实现至少保留下列 action 名称与触发时机：

- `issue.created`
  - 创建 issue 成功后写入
- `issue.updated`
  - issue 基础字段更新成功后写入
- `issue.comment_added`
  - update 携带 comment 且成功落库后写入
- `issue.review_decision_recorded`
  - reviewer decision 记录成功后写入
- `issue.human_intervention_required`
  - reviewer decision 进入需要人工介入的 blocked 场景后写入
- `issue.deleted`
  - 删除 issue 成功后写入
- `issue.checked_out`
  - checkout 成功后写入
- `issue.released`
  - release 成功后写入
- `issue.code_committed`
  - commit 成功后写入

## Approval 状态流转

当前第一批实现至少按以下状态语义对齐 Rudder：

- `pending`
- `approved`
- `rejected`
- `needs_revision`

### Create

- approval 创建时默认状态为 `pending`

### Approve

- 只有 board 身份允许 approve
- approve 成功后状态进入 `approved`
- 如果 approval 关联 issue，且关联 issue 当前状态为 `blocked`
  - 有 assignee 时恢复到 `in_progress`
  - 无 assignee 时恢复到 `todo`

### Reject

- 只有 board 身份允许 reject
- reject 成功后状态进入 `rejected`

### Request Revision

- 只有 board 身份允许 request revision
- request revision 成功后状态进入 `needs_revision`

### Resubmit

- requester 为 agent 时，只允许 requester 自己 resubmit
- resubmit 成功后状态回到待处理轨道，B 在实现时保持与 Rudder 当前持久化结果一致

## Approval activity action

当前实现至少保留下列 action 名称与触发时机：

- `approval.created`
  - 创建 approval 成功后写入
- `approval.approved`
  - approve 成功后写入
- `approval.rejected`
  - reject 成功后写入
- `approval.revision_requested`
  - request revision 成功后写入
- `approval.resubmitted`
  - resubmit 成功后写入
- `approval.comment_added`
  - approval comment 成功后写入
- `issue.approval_linked`
  - approval 创建并成功关联 issue 后，对每个关联 issue 写入
- `approval.linked_issue_assignee_wakeup_queued`
  - approve 后关联 issue assignee wakeup 入队成功时写入
- `approval.linked_issue_assignee_wakeup_failed`
  - approve 后关联 issue assignee wakeup 入队失败时写入
- `approval.requester_wakeup_queued`
  - approve 后 requester wakeup 入队成功时写入
- `approval.requester_wakeup_failed`
  - approve 后 requester wakeup 入队失败时写入

## B 实现时必须保持的边界

- 不改现有 action 名称
- 不改现有状态值命名
- 不把 review decision 的状态映射改成自定义语义
- 不把 approval 通过后的 blocked issue 恢复规则改成别的状态
- 不删除当前依赖权限身份的守卫条件

## 当前阶段不展开的内容

以下内容留到后续阶段按实现阻塞点继续补：

- chat approval 的完整分支行为
- 更细的 wakeup payload 结构
- 完整 activity payload 字段级清单
- runtime 执行链路与 workflow 的联动细节
