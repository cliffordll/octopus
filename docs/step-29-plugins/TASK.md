# Step 29: Plugin Framework

状态：进行中

## 已提前完成

- 内置技能目录中已经包含 `create-plugin` skill 及中文说明，用于保留上游 plugin authoring 相关知识。
- Runtime/agent skills 管理和 organization skills 管理已能发现、同步、启用技能，但这不是 plugin framework。

这些只属于技能内容和运行时技能管理，不代表插件子系统已经实现。

## 上游证据

上游参考实现已有独立 plugin framework，不是简单扩展点。开发前必须优先核对：

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
- plugin authoring scaffold package
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

## 开发任务拆分

### 29A: Contract、manifest 与 catalog

- 对齐上游 `PaperclipPluginManifestV1`、capability、UI slot、job、webhook、tool 和 config schema 结构。
- 增加 shared type、validator、错误结构和 API path 常量。
- 建立 bundled plugin catalog，能从本地约定目录读取 manifest、entrypoints、README/metadata 和 example 标记。
- 管理 API 先支持只读列表、available/examples、manifest detail 和基础 validation error。
- 验收：contract tests 覆盖 manifest 解析、capability 枚举、UI slot/job/webhook/tool schema 和 catalog response。

### 29B: Database、registry 与 lifecycle

- 增加 plugin 迁移和 schema：`plugins`、`plugin_config`、`plugin_state`、`plugin_entities`、`plugin_jobs`、`plugin_job_runs`、`plugin_logs`、`plugin_webhook_deliveries`、`plugin_organization_settings`。
- 实现 registry service：安装记录、列表、按状态过滤、配置读写、实体映射、job/webhook/log 查询。
- 实现 lifecycle service：`installed`、`ready`、`disabled`、`error`、`upgrade_pending`、`uninstalled` 状态流转。
- 管理 API 覆盖 install、enable、disable、uninstall/purge、upgrade、health、config、logs、dashboard。
- 验收：migration tests、registry tests 和 workflow tests 覆盖 install -> enable -> ready -> disable -> enable -> uninstall/purge。

### 29C: Worker、host services 与 tools

- 实现 worker manager 和 JSON-RPC 边界：activation/deactivation、`getData`、`performAction`、`validateConfig`、`handleWebhook`、tool execution、graceful shutdown。
- 实现 plugin host services：config、state、entities、activity/log、organization/project/issue/workspace 只读或受控写入能力。
- 实现 capability gating，插件只允许调用 manifest 声明的 host capability。
- 实现 plugin tools registry/dispatcher，使 agent 能发现并调用 plugin-contributed tools。
- 验收：worker RPC、capability denied、tool discovery/execution 和错误映射有 contract/workflow tests。

### 29D: Jobs、webhooks、state 和 logs

- 实现 plugin state store、job store、job scheduler/coordinator 和 job run 持久化。
- 实现 webhook ingress：记录 delivery、校验 ready 状态和 declared endpoint，再转发给 worker。
- 实现 plugin logs 聚合、dashboard 统计和 stream/event 更新。
- 验收：job trigger/run record、webhook delivery success/failure、state read/write/delete、logs/dashboard tests。

### 29E: UI bridge 与静态资源

- 实现 plugin UI 静态资源路由和 same-origin trusted JS 加载边界。
- 实现 UI contributions registry，覆盖 page、settingsPage、detailTab、dashboardWidget、sidebar/projectSidebarItem、commentAnnotation/action 等上游已声明 slot。
- 实现 bridge data/action API、UI stream/SSE 和基础 host context 注入。
- 验收：UI contribution metadata、bridge `getData`/`performAction`、stream 基础响应和 slot filtering tests。

### 29F: Bundled plugins、SDK 兼容和文档

- 添加 bundled examples 的本地目录约定、安装来源和构建/加载说明。
- 优先让 server 加载已构建的上游插件结构；Python 版 SDK/脚手架只定义兼容边界，不在首轮承诺完整作者体验。
- 补齐开发文档：安装插件、配置插件、调试 worker、查看日志、使用插件 tool、插件 UI bridge 限制。当前文档入口：`docs/step-29-plugins/AUTHORING.md`。
- 验收：Linear 和三个 example 插件能作为本地 fixture 通过 catalog、install、enable、config、worker/UI smoke。

## 需要添加的插件

Step 29 的目标不是只做一个空框架。插件框架必须覆盖真实一方集成会用到的安装、配置、secret 引用、worker、tool、job、webhook、entity mapping、UI bridge、日志和调试链路。Linear 与 bundled examples 用于对照和 smoke；GitHub、Slack、Jira、Notion 列为 Step 29 必做集成对象，但生产级外部系统语义必须先落 manifest、capability、config schema、数据映射、UI surface、权限/secret 边界和验收用例，不能凭空硬编码。

### 必须添加

- Linear：第一方业务插件，对照 `packages/plugins/examples/plugin-linear/`。用途是从 Linear 浏览 issue、批量导入到 Octopus project、保存 Octopus issue 与 Linear issue 的一对一关联，并在 issue 详情中展示 linked Linear issue。首轮不做双向同步、评论同步、webhook 或状态回写。插件 ID 以实际 manifest 为准，不在规划文档中重命名。
- GitHub：必做一方集成对象。首轮验收范围是 repository/PR/issue 读取能力边界、PR/issue webhook ingress 契约、GitHub issue/PR 与本地 issue 的 entity mapping、agent tool 查询仓库上下文、config/secret 引用和日志。进入生产级实现前必须确认 GitHub App、PAT 或 fine-grained token 的授权方式。
- Slack：必做一方集成对象。首轮验收范围是 workspace 安装配置、bot token/signing secret 引用、消息通知或 command ingress 契约、channel/org 映射、approval/incident 事件推送边界和 agent 对话入口能力边界。
- Jira：必做一方集成对象。首轮验收范围是 issue import、project/status mapping、comment/status sync 契约、webhook ingress、agent tool 查询 issue 和配置 schema。进入生产级实现前必须区分 Jira Cloud 与 Data Center 字段/权限差异。
- Notion：必做一方集成对象。首轮验收范围是 database/page 读取、知识库检索、page-to-issue import、agent tool 查询和 workspace 授权边界。进入生产级实现前必须确认 Notion database schema 映射。

### 必须添加为 bundled example / 验收 fixture

- Plugin Authoring Smoke Example：最小作者体验 smoke 插件，对照 `packages/plugins/examples/plugin-authoring-smoke-example/`。用途是验证 SDK authoring、worker、state read/write、events subscribe 和 dashboard widget 的最小链路。插件 ID 以实际 manifest 为准。
- File Browser Example：workspace/UI 示例插件，对照 `packages/plugins/examples/plugin-file-browser-example/`。用途是验证 project sidebar item、project detail tab、workspace file list/read/write、comment annotation 和 comment context menu。插件 ID 以实际 manifest 为准。
- Kitchen Sink Example：综合回归插件，对照 `packages/plugins/examples/plugin-kitchen-sink-example/`。用途是覆盖 page、settings、dashboard、sidebar、detail tabs、comment surfaces、bridge data/action、events、jobs、webhooks、tools、streams、state、entities、metrics、activity、workspace 和受控 process demo。插件 ID 以实际 manifest 为准。

### 暂不添加

- 生产级第三方插件 marketplace：本步骤只实现本地单实例 plugin framework、bundled/local plugin 管理和一方集成的基础能力边界，不承诺云端多实例 artifact 分发或 marketplace 审核/发布流程。
- Stripe 等非当前核心工作流插件：除非后续明确进入 Octopus 当前产品范围，否则不把 billing 产品模型塞进 plugin framework 首轮。

## 剩余待开发

- 已完成 plugin schema、migration、registry/lifecycle service、worker manager、tool dispatcher、job/webhook/state/log store 和基础 plugin UI bridge。
- 已添加 bundled plugin fixtures 和 Step 29 authoring/operations 文档。
- 已补齐 worker activation/deactivation 边界、job trigger coordinator、webhook ready/endpoint/capability 校验与 worker 转发、host services capability gating、config/state/log/entity mapping 受控调用面。
- 仍需补齐 scheduler/coordinator 常驻运行、UI stream 增量事件、SDK/脚手架包实现和一方集成插件生产级 provider 行为。
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
