# Step 29: Plugin Framework

状态：待开发

## 已提前完成

- 内置技能目录中已经包含 `create-plugin` skill 及中文说明，用于保留上游 plugin authoring 相关知识。
- Runtime/agent skills 管理和 organization skills 管理已能发现、同步、启用技能，但这不是 plugin framework。

这些只属于技能内容和运行时技能管理，不代表插件子系统已经实现。

## 上游证据

上游 `D:\coding\rudder` 已有独立 plugin framework，不是简单扩展点。开发前必须优先核对：

- `doc/plugins/PLUGIN_SPEC.md`
- `server/src/routes/plugins.ts`
- `server/src/routes/plugins.operations-routes.ts`
- `server/src/bootstrap/plugin-host-runtime.ts`
- `server/src/services/plugin-registry.ts`
- `server/src/services/plugin-lifecycle.ts`
- `server/src/services/plugin-loader*.ts`
- `server/src/services/plugin-worker-manager.ts`
- `server/src/services/plugin-tool-dispatcher.ts`
- `server/src/services/plugin-job-*.ts`
- `server/src/services/plugin-state-store.ts`
- `server/src/services/plugin-host-services.ts`
- `packages/db/src/schema/plugins.ts`
- `packages/db/src/schema/plugin_*.ts`
- `packages/plugins/sdk/`
- `packages/plugins/create-rudder-plugin/`
- `packages/plugins/examples/plugin-linear/`

## 目标

实现上游 server plugin framework 的 Python 兼容版本，使 Octopus 能在本地单实例部署中管理、加载和调用插件，同时明确不承诺上游尚未完成的云端多实例插件分发模型。

## 任务

- 实现 plugin manifest、shared type、状态枚举和 validator。
- 增加 plugin 相关迁移和数据库模型，包括 `plugins`、`plugin_config`、`plugin_state`、`plugin_entities`、`plugin_jobs`、`plugin_job_runs`、`plugin_logs`、`plugin_webhook_deliveries`、`plugin_organization_settings`。
- 实现 plugin registry service，支持安装记录、列表、按状态过滤、配置、实体映射、job 和 webhook delivery 持久化。
- 实现 lifecycle service，支持 `installed`、`ready`、`disabled`、`error`、`upgrade_pending`、`uninstalled` 状态流转。
- 实现管理 API，覆盖列表、available/examples、安装、启用、禁用、卸载、升级、健康检查、配置、日志和 dashboard。
- 实现 worker RPC 边界，支持 activation/deactivation、`getData`、`performAction`、`validateConfig`、`handleWebhook`、tool execution 和 graceful shutdown。
- 实现 plugin tools registry/dispatcher，使 agent 能发现并调用 plugin-contributed tools。
- 实现 plugin jobs 和 scheduler/coordinator，记录 job run 并支持手动触发。
- 实现 webhook ingress，记录 delivery 并转发给 plugin worker。
- 实现 plugin state store、host services、secrets/config 能力边界和日志归集。
- 实现 plugin UI 静态资源路由、UI contributions、bridge data/action 和 SSE stream。
- 规划 Python 版本 SDK/脚手架兼容边界；优先保证 server 能加载已约定结构的插件，再考虑作者工具。
- 补齐一方插件目录约定，Linear 插件作为上游对照目标，不在无证据情况下改成 Octopus 私有插件模型。

## 剩余待开发

- 当前没有 plugin schema、migration、registry/lifecycle service、worker manager、tool dispatcher、job/webhook/state/log store 或 plugin UI bridge。
- 当前没有 `server/routes/plugins.py`、`plugin-ui-static`、plugin operations routes。
- 当前没有 Python 版 plugin SDK/authoring scaffold，仅有内置 `create-plugin` skill 文档可作后续参考。

## 边界

- 插件是全局/operator-driven 安装，不是 project-local `.plugins`。
- 插件运行时默认按上游早期模型面向本地或自托管持久化部署，不提供多实例云端 artifact 分发。
- 插件 UI 按上游 same-origin trusted JS 边界实现，不擅自宣称安全沙箱。
- 插件不得覆盖核心路由、修改核心授权/预算、直接访问业务数据库或执行第三方 DB migrations。
- 插件 secrets/env 解析依赖 Step 30 的 actor/access/secret 边界；未完成前只能提供明确的开发期兼容行为。
- 插件 cost/budget/activity 归集依赖 Step 20/25/27/28 已有 observability、activity、成本与治理记录，不在本步骤重新定义治理模型。

## 验收

- Contract tests 覆盖 plugin API 路径、payload、状态枚举、配置校验和错误结构。
- Migration tests 覆盖 plugin 相关表、索引、外键和级联行为。
- Workflow tests 覆盖 install -> enable -> ready -> disable -> enable -> uninstall/purge 状态流转。
- Workflow tests 覆盖 plugin config 保存、schema 校验、configChanged/restart fallback 行为。
- Workflow tests 覆盖 tool discovery/execution、job trigger/run record、webhook delivery 和 worker RPC 错误映射。
- Workflow tests 覆盖 UI contributions、bridge data/action 和 stream 的基础响应。
- 文档记录上游未完成或不纳入的能力：云端多实例插件分发、真正前端沙箱、插件资产上传/读取、第三方 DB migration。
