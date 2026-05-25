# Step 5 Ownership Draft

## 状态

- Draft
- 待 B 进入 ownership 与 scope 校验实现时收口

## 目标

先把 organization ownership 建成基础边界，确保请求入口和后台任务不会越权处理非本 pod 的组织数据。

## 本阶段范围

- organization ownership 校验服务
- 请求入口的 organization scope 校验
- 后台任务执行前的 ownership 过滤
- lease / pod 归属相关最小防护

## A 线需要冻结的内容

- ownership 拒绝语义
- 正确 pod / 错误 pod / lease 失效的测试断言
- organization scope 在 read API 和 background task 中的统一规则

## B 线实现重点

- 在请求入口和任务入口都接入 ownership 校验
- 不允许先扫全库再在末尾做 ownership 过滤

## 验收 demo

- Demo 1：owned organization 请求成功
- Demo 2：foreign organization 请求被拒绝
- Demo 3：后台任务执行前先过滤 ownership
- Demo 4：展示 ownership 测试结果

## 待确认项

- ownership 信息的持久化来源
- lease 续约与失效时的最小行为
- 背景任务是否需要统一入口封装 ownership guard

## 当前不冻结

- 完整 failover 策略
- 多 pod 恢复编排
- 全量调度系统行为
