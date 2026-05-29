# Step 19: Basic Observability / Debug Visibility

状态：待开发

## 目标

在真实 Auth 接入前，先补齐开发和联调需要的基础可见性，使 chat、run、runtime、workspace 的问题能被定位。

本步骤只做调试可见性，不做完整恢复、生产级指标或全链路兼容收口。

## 任务

- 补齐 run events、runtime stdout/stderr 摘要、错误码、错误摘要和 context snapshot 的查询可见性。
- 补齐 workspace operation / work product 与 run/message 的基础关联查询。
- 补齐 chat execution error 的可读响应，避免 UI/CLI 只能看到空消息或泛化失败。
- 梳理 activity、run event、runtime result、workspace operation 四类记录的定位关系，并写入文档。
- 保持本地开发 actor 和模拟数据结构与后续真实 actor 兼容。

## 边界

- 不实现真实 Auth / Actor / Access，归 Step 23。
- 不实现完整 Recovery / Compatibility 矩阵，归 Step 24。
- 不实现 budget/cost 治理，归 Step 20/21。
- 不新增外部观测系统依赖；本阶段以数据库记录和服务端响应可见性为主。

## 验收

- Tests 覆盖 run 失败、runtime stderr/stdout 摘要、workspace operation 关联和 chat execution error 查询。
- Tests 覆盖可见性接口的 organization scope。
- 文档说明 chat、run、workspace、activity 的调试路径。
