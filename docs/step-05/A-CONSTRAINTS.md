# Step 5 A Constraints

## 1. 目标

Step 5 的目标是先把 `organization ownership` 建成最小可执行边界，确保：

- 请求入口不会处理非本 pod 的 organization
- 后台任务不会扫描或执行非本 pod 的 organization
- Step 6 的 read API 和 Step 7 的 mutation workflow 都建立在同一套 ownership 规则上

这一步只做四件事：

- 固定 ownership / lease 的最小持久化来源
- 固定请求入口和任务入口的 ownership guard 位置
- 固定 wrong pod / expired lease 的拒绝语义
- 固定 ownership 的最小测试矩阵

## 2. 本步输入

Step 5 只能基于以下输入推进：

- [docs/DESIGN.md](D:/coding/octopus/docs/DESIGN.md)
- [docs/FEATURE.md](D:/coding/octopus/docs/FEATURE.md)
- [docs/step-02/SERVER-SKELETON.md](D:/coding/octopus/docs/step-02/SERVER-SKELETON.md)
- [docs/step-03/A-CONSTRAINTS.md](D:/coding/octopus/docs/step-03/A-CONSTRAINTS.md)
- [docs/step-03/SHARED-CONTRACT.md](D:/coding/octopus/docs/step-03/SHARED-CONTRACT.md)
- [docs/step-04/A-CONSTRAINTS.md](D:/coding/octopus/docs/step-04/A-CONSTRAINTS.md)
- [docs/step-04/DATABASE-MAPPING.md](D:/coding/octopus/docs/step-04/DATABASE-MAPPING.md)

输入关系必须明确：

- `5.1 ownership source` 直接以 `DESIGN.md` 6.3 为核心输入
- `5.2 request guard` 同时受 Step 2 server skeleton 与 Step 4 分层约束限制
- `5.3 background filtering` 直接受 `DESIGN.md` 中 pod-local single-writer execution 约束限制
- `5.4 tests` 以 `FEATURE.md` 和 `DESIGN.md` 的 ownership demo / safety 要求为准

## 3. 本步范围

本步只覆盖：

- ownership / lease 的最小基础设施表边界
- `packages/database/queries/` 下 ownership 读取入口
- `server/` 内请求入口的 ownership guard
- 后台任务或后台扫描在执行前的 ownership 过滤入口
- ownership 相关 contract / ownership tests

本步不做：

- 完整 failover 编排
- 跨 pod 迁移流程
- lease 自动续约策略优化
- 全量 read API
- mutation workflow 细节
- 外层控制系统实现

## 4. 输出要求

Step 5 完成后，B 至少要交付：

- 一张 ownership / lease 基础设施表映射
- 一个 ownership 查询入口
- 一个请求入口 ownership guard
- 一个后台任务 ownership 过滤入口
- 至少一条 owned success / foreign reject 的最小调用链
- 至少一组 lease expired 的最小测试

## 5. 5.1 Ownership Source 约束

### 5.1 A 已冻结的边界

- ownership 真相必须持久化在数据库中，不能只靠进程内缓存或外部代理头
- ownership 以独立基础设施表承载，不能混入 `organizations` 业务表字段
- 第一版 ownership 记录最少必须包含：
  - `organization_id`
  - `pod_id`
  - `lease_version`
  - `acquired_at`
  - `last_heartbeat_at`
  - `expires_at`
- Step 5 只要求“读取并校验当前 ownership”，不要求实现完整续约 loop
- `organization_id` 在 ownership 表中必须唯一，表达“同一时刻一个 organization 只归一个 pod”

### 5.2 B 必须落的最小文件边界

`packages/database/schema/` 下至少新增：

- `organization_ownership.py`

`packages/database/queries/` 下至少新增：

- `organization_ownership.py`

文件职责要求：

- schema 文件只定义 ownership 表结构和局部约束
- query 文件只定义 ownership 读取和最小过滤查询
- 不在 query 层写 HTTP 拒绝语义
- 不在 schema 文件里写 lease 续约 workflow

### 5.3 B 当前可以做

- 建 ownership 表映射
- 建按 `organization_id` 读取 ownership 的 query
- 建按 `pod_id` 列出 owned organizations 的 query
- 建“lease 是否仍有效”的最小判断输入

### 5.4 B 当前不能做

- 把 ownership 信息写回 `organizations`
- 不落表、只靠内存 mock ownership
- 直接实现复杂 failover 接管策略
- 让外层代理 header 替代数据库 ownership 真相

## 6. 5.2 Request Guard 约束

### 6.1 A 已冻结的边界

- 所有 organization-scoped 请求在进入业务 service 前必须经过 ownership guard
- wrong pod 请求必须在入口侧被拒绝，不能先进入业务查询后再兜底拒绝
- ownership guard 位置在 `route/dependency -> ownership service -> ownership query`
- route 不直接拼 ownership SQL
- validator 不负责 ownership 判断
- board-scoped 非 organization 请求不属于本步主要目标，不要求被 ownership guard 改写

### 6.2 拒绝语义

Step 5 先冻结以下最小语义：

- owned organization: 允许继续进入业务 service
- foreign organization: 返回 `403 Forbidden`
- ownership record missing: 返回 `403 Forbidden`
- lease expired: 返回 `409 Conflict`

错误 detail 文案在 Step 5 不要求一次定死所有文案，但必须能区分：

- wrong pod / not owned
- lease expired / ownership stale

### 6.3 B 必须落的最小文件边界

`server/` 下至少应有：

- `services/ownership.py`
- 一个可被 route / dependency 复用的 ownership guard 入口

命名可以微调，但职责不能漂：

- `services/ownership.py` 承载 ownership 判断语义
- guard 入口承载 HTTP 层接线
- route 只依赖 guard 或 ownership-aware service，不直连 query

### 6.4 B 当前可以做

- 在 dependency 或 guard 模块里接 ownership 校验
- 让第一批 organization-scoped route 先走统一 ownership 入口
- 用 `Settings` 提供当前 pod identity 配置，例如 `OCTOPUS_POD_ID`

### 6.5 B 当前不能做

- 把 ownership 判断散进每个 route handler
- 把 wrong pod 语义下沉到 query 层
- 让 service 自己创建 session 再查 ownership
- 用 request 参数伪造当前 pod identity

## 7. 5.3 Background Filtering 约束

### 7.1 A 已冻结的边界

- 后台任务必须先拿“当前 pod 拥有哪些 organizations”，再决定扫描或执行
- 不允许先扫全库业务表再在末尾过滤 ownership
- 后台任务和请求入口必须使用同一 ownership 真相来源
- Step 5 只要求建立过滤入口，不要求完整后台框架

### 7.2 B 必须落的最小文件边界

至少需要一个可复用入口，职责等价于：

- `list_owned_organization_ids(pod_id, now)`

如果要放在 `server/`，只能是：

- `services/ownership.py`
- 或 `background/` 下的最小 guard / filter 模块

### 7.3 B 当前可以做

- 为后台扫描提供 `owned organization ids` 查询
- 在假定任务入口或最小后台入口演示先过滤再处理

### 7.4 B 当前不能做

- 先查 `issues` / `approvals` / `activity_log` 全表再按 org 过滤
- 让每个后台任务各自实现一套 ownership 规则

## 8. 分层硬约束

Step 5 必须满足以下硬约束：

- `server/routes` 不直接查询 ownership 表
- `server/services` 不直接创建 session
- `packages/database/queries` 不返回 HTTP response shape
- validator 不负责 ownership
- ownership 表属于基础设施表，不混入业务表语义
- 请求入口和后台任务入口使用同一 ownership 真相来源
- wrong pod 拒绝发生在业务 service 之前

## 9. B 的实现顺序

B 在 Step 5 的建议顺序固定为：

1. `5.1 ownership source`
2. `5.2 request guard`
3. `5.3 background filtering`
4. `5.4 tests`

原因：

- ownership 真相来源不固定，guard 规则就会漂
- 请求入口先固定，Step 6 read API 才不会返工
- 后台过滤必须建立在统一 ownership query 之上

## 10. 验收标准

Step 5 验收时必须同时满足：

- ownership / lease 真相来源已落在数据库基础设施表
- 请求入口已存在统一 ownership guard
- wrong pod / missing ownership / expired lease 的拒绝语义已固定
- 后台任务存在“先按 owned organizations 过滤再执行”的入口
- 没有先扫全库后过滤 ownership
- ownership tests 能覆盖 owned / foreign / expired lease 三类结果

## 11. 验收 Demo

- Demo 1：展示 ownership 表结构和 query 入口，说明 `organization_id -> pod_id -> expires_at` 如何表达归属
- Demo 2：展示一个 owned organization 请求成功，说明 guard 路径
- Demo 3：展示一个 foreign organization 请求被 `403` 拒绝
- Demo 4：展示一个 expired lease 请求被 `409` 拒绝
- Demo 5：展示后台任务先列 owned organization ids，再进入业务处理

## 12. 测试冻结口径

Step 5 最少必须冻结以下测试断言：

- owned organization request success
- foreign organization request rejected with `403`
- missing ownership request rejected with `403`
- expired lease request rejected with `409`
- background task only receives owned organizations

测试目录建议至少包括：

- `tests/ownership/`
- 或 `tests/contract/` 中独立 ownership contract

但无论放哪里，都必须覆盖上面 5 类断言。

## 13. 本步后的衔接关系

Step 5 完成后：

- Step 6 会在 read API 中直接消费 ownership guard
- Step 7 会在 mutation workflow 中复用同一 ownership 规则
- Step 10 会在此基础上继续补强 wrong-route / failover / lease 保护

所以 Step 5 的目标不是把多 pod 系统一次做完，而是先冻结 ownership 的真相来源、入口位置和拒绝语义，让后续读写能力都建立在同一边界上。
