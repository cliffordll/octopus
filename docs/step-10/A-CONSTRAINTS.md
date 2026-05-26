# Step 10 A Constraints

## 1. 当前状态

当前文件是草稿版本。

用途是先把 `projects / goals / agents` 三条主对象管理线的边界拆清楚，不在这一步提前冻结所有执行面、资源面和治理面的最终细节。等 Step 11 运行 / 工作区、Step 12 聊天 / 存储、Step 13 资源封装继续落地后，再把这些主对象与后续系统的交叉规则逐项收紧。

## 2. 目标

Step 10 的目标是补齐三类核心控制面主对象，并固定它们与现有组织、任务、审批链路的第一批关系：

- project management
- goal management
- agent management

这一步要解决的问题不是横切治理，而是把主对象本身立起来，让后续 run / workspace / chat / plugin 都有稳定挂靠点。

## 3. 本阶段范围

本步只覆盖：

- `projects`
- `goals`
- `agents`
- 它们与 `organizations / issues / approvals / runs` 的第一批对象关系
- 这些主对象各自的 list / detail / create / update / status 边界

本步至少要能回答：

- project 如何挂在 organization 下
- goal 如何挂在 project 或 organization 范围下
- agent 如何创建、配置、启停和与组织绑定
- issue / approval / run 后续要如何引用这些主对象

## 4. A 线必须先冻结的内容

以下内容必须先在约束和 spec 中冻结，再允许进入实现：

- project / goal / agent 的最小字段清单
- 三类对象的最小状态语义
- project / goal / agent 与 organization 的归属边界
- issue / approval / run 对三类对象的最小引用方式
- 哪些写能力属于第一批必须落地，哪些延后

## 5. B 线实现边界

- 不允许把 project / goal / agent 混进 `orgs.py` / `issues.py` / `approvals.py` 继续散写
- 不允许在没有冻结 shared contract 前先拍脑袋发明 payload
- 不允许把资源封装、runtime orchestration、storage adapter 逻辑提前混入本步
- 先把主对象 CRUD / 状态 / 关系边界立稳，再接 Step 11+ 的执行和资源主线

## 6. 验收 demo

- Demo 1：演示 project / goal 的最小管理流程
- Demo 2：演示 agent 创建、配置、启停或组织绑定流程
- Demo 3：展示 project / goal / agent 与 issue 的第一批关系
- Demo 4：展示 contract / workflow 测试结果

## 7. 待确认项

- goal 是否必须挂在 project 下，还是允许直接 organization-scoped
- project / goal 的最小状态机是否一步冻结
- agent 配置字段的第一批范围是否只做最小可运行集合
- approval / run 在本步是否只保留外键关系，不展开完整 workflow

## 8. 与前后步骤的边界

- 继续消费 Step 7 的 organization 边界
- 继续消费 Step 8 的 issue 边界
- 继续消费 Step 9 的 approval 边界
- 为 Step 11 的 run / workspace 提供主对象挂靠点
- 为 Step 13 的 skill / plugin / agent resource bindings 提供 agent 主对象基础

## 9. 当前不冻结

- runtime / workspace 最终状态和生命周期
- chat / attachment / artifact / storage 细节
- skill / plugin / registry 元数据细节
- proxy / actor context、budget / cost / activity 的治理收口
- observability / recovery / compatibility diff
