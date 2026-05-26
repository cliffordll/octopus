# Step 14 A Constraints

## 当前状态

当前文件是草稿版本。

用途是先把配置、上下文、预算 / 成本 / 活动治理的系统性方向定住，不在这一步提前把所有治理字段写死。等 Step 10 到 Step 13 的主对象、执行面、协作面和资源面基本可跑后，再把系统级规则逐项收紧。

## 目标

统一收口以下治理能力：

- 配置模型
- proxy / actor context
- budget / cost / activity

## 本阶段范围

- `server/config.py`
- proxy context / actor context 注入与消费
- budget / cost / activity 统一归集
- 与 database / storage / runtime / workspace / resources 的配置连接点
- 与 `projects / goals / agents / runs / chats / artifacts` 的治理连接点

## A 线必须先冻结的内容

- 统一配置模型的最小分层方式
- proxy / actor context 的最小进入点和语义
- budget / cost / activity 的统一口径
- 哪些治理规则必须在多模块里统一执行
- 配置、上下文和治理规则跨 HTTP、后台任务与离线流程的最小共享方式

## B 线实现边界

- 配置读取必须集中，不允许继续散落
- proxy / actor context 不得混入业务 payload
- budget / cost / activity 不得由各模块各自解释
- 不在本步重新定义 project / goal / agent / run / chat 资源本身的业务语义

## 验收 demo

- Demo 1：演示配置模型覆盖 database / storage / runtime / workspace
- Demo 2：演示 proxy / actor context 参与真实链路
- Demo 3：演示 budget / cost / activity 的统一归集
- Demo 4：展示 contract / workflow / pyright 结果

## 待确认项

- context 在 HTTP 与后台任务中的统一进入方式
- budget / cost 的最小聚合模型
- activity 在治理层与业务层的边界
- auto-migrate、runtime provider、storage backend 等配置是否统一纳入同一层级模型

## 与前后步骤的边界

- 消费 Step 10 的 project / goal / agent 主对象边界
- 消费 Step 11 的 run / workspace 执行事件
- 消费 Step 12 的 chat / attachment / artifact / storage 事件
- 消费 Step 13 的 skill / plugin / agent resource 装配边界
- 不替代前序步骤的业务对象 contract，只统一其配置、上下文和治理口径

## 当前不冻结

- observability / recovery / compatibility diff 的最终口径
- 全量生产运维体系
