# Step 8 A Constraints

## 当前状态

当前文件是草稿版本。

用途是先给出规划与执行模块的整体边界，不在这一步提前把所有对象的字段和状态机一次写死。等 Step 7 的控制面业务主线真正落地后，再按项目、目标、智能体、运行、工作区的真实阻塞点收紧。

## 目标

将规划对象和执行对象合并推进，优先补齐：

- 项目管理
- 目标管理
- 智能体管理
- 运行 / 心跳运行
- 工作区生命周期

## 本阶段范围

- `projects`
- `goals`
- `agents`
- `heartbeat_runs`
- runtime orchestration
- workspace allocation / release / recovery
- 上述对象之间的绑定关系和执行关系

## A 线必须先冻结的内容

以下内容当前仍是草稿收口方向：

- project / goal / agent 的最小字段与状态语义
- agent 与 runtime / workspace 的绑定边界
- heartbeat run 的最小状态机
- workspace 分配、占用、释放、失败恢复的最小语义
- 规划对象与执行对象之间的关联规则

同时，Step 8 继续承接来自历史 workflow notes 的任务管理约束，后续收紧时至少要覆盖：

- issue 第一批状态值：
  - `todo`
  - `in_progress`
  - `in_review`
  - `blocked`
  - `done`
- reviewer decision 到 issue status 的最小映射：
  - `approve` -> `done`
  - `request_changes` -> `in_progress`
  - `blocked` -> `blocked`
  - `needs_followup` -> 不直接改 issue status
- reviewer decision 只允许在：
  - `in_review`
  - `blocked`
  这两个前置状态下发生
- issue reopen 语义：
  - 已关闭 issue 在 update 时如果显式要求 reopen，且未显式指定新 `status`
  - 默认重新打开到 `todo`
- issue activity action 至少保留：
  - `issue.created`
  - `issue.updated`
  - `issue.comment_added`
  - `issue.review_decision_recorded`
  - `issue.human_intervention_required`
  - `issue.deleted`
  - `issue.checked_out`
  - `issue.released`
  - `issue.code_committed`

## B 线实现边界

- project / goal / agent 与 run / workspace 仍按资源边界分层，不写成单个巨型 service
- runtime 继续通过集中 shared contract 接入，不让 provider 差异泄漏到业务层
- workspace 不得只停留在 schema 字段，要有真实分配与恢复路径
- 执行对象和规划对象之间的关系必须能被测试验证
- issue workflow 相关实现时，不得：
  - 自定义修改 issue 状态值命名
  - 自定义改写 reviewer decision 到 status 的映射
  - 删除上述 issue activity action 名称
- issue checkout / commit 相关历史约束继续保留为后续收紧方向：
  - project 处于 paused 状态时，checkout 必须拒绝
  - agent 只能以自己的 agent 身份 checkout
  - `commit` 只允许 agent 身份执行

## 验收 demo

- Demo 1：演示 project / goal 中至少一个真实管理流程
- Demo 2：演示 agent 创建、配置或绑定的一条真实链路
- Demo 3：演示 heartbeat run 创建、推进、结束的一条真实链路
- Demo 4：演示 workspace 分配、释放或失败恢复的一条真实链路

## 待确认项

- project / goal 与 issue 的最小双向关系范围
- agent 的最小配置模型与启停语义
- heartbeat run 与 issue / goal / project 的关联字段口径
- workspace 失败恢复与 failover 的边界切分
- issue checkout / release / commit 是继续留在任务管理还是拆到执行链路
- issue reviewer decision、comment、reopen 是否一步冻结完整 payload 语义

## Step 7 完成后再补

- project / goal / agent 第一批 shared types 边界
- run result / transcript / artifact 与 workspace 的真实收口方式
- fake runtime 和测试注入边界
- 规划对象与执行对象的最小回归测试矩阵
- issue 状态流转、comment、review decision 的最终字段级清单
- issue activity payload 的最小字段集

## 当前不冻结

- chat 会话与消息细节
- attachment / artifact 存储语义
- skills / plugins 资源装配
- observability / recovery 的最终收口方案
