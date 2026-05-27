# Step 12: Goal 管理

状态：待开发

## 调整原因

上游 Goal 具有 `ownerAgentId` 关系，并在创建和更新时校验 owner agent 与 goal 属于相同 organization。本步骤后移到 Agent 管理之后，以完整实现该已确认关系，不在 Goal 初次交付中留下已知缺口。

## 已确认上游范围

- Goal 字段包含 `title`、`description`、`level`、`status`、`parentId` 与 `ownerAgentId`。
- `level` 为 `organization`、`team`、`agent`、`task`；`status` 为 `planned`、`active`、`achieved`、`cancelled`。
- HTTP surface 包含 organization 内列表、详情、dependencies、创建、更新和删除。
- Service 校验 parent 同 organization、禁止自身或循环父级关系，并校验 owner agent 同 organization。
- Project 通过 `project_goals` 支持多 Goal 关联，同时保留 legacy `project.goalId`；Issue 已有 nullable `goalId` 关系字段。

## 任务

- 实现 goal contract、schema/query、migration、service 与 API。
- 接入 Goal 父子层级和 `ownerAgentId` 引用校验。
- 接入 Project `goalIds` / `goals` 聚合与 legacy `goalId` 同步行为。
- 按当前已实现领域接入 Issue/Project/子 Goal 的 dependency 预览与删除阻塞。

## 延后边界

- Automation 目前不在主线步骤中；确认纳入 server 兼容范围后，再接入 Goal dependency。
- Cost/Finance 依赖归随治理能力落地后接入；Step 16 需补充 Goal 删除阻塞行为。
- 本步骤不得伪造尚不存在的依赖表或空实现来宣称完整 dependency 已实现。

## 验收

- Tests 覆盖 Goal CRUD、状态/层级校验、owner agent 与跨 organization 拒绝行为。
- Tests 覆盖 Project 多 Goal 关联、Issue 关联，以及本阶段可实现的 dependency/delete 行为。
