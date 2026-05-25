# Step 10 Hardening Draft

## 状态

- Draft
- 待进入 hardening 阶段时收口

## 目标

补齐 failover、安全性、恢复性、兼容 diff 和关键回归验证，让 Octopus 进入可持续迭代的稳定阶段。

## 本阶段范围

- ownership 错路由防护补强
- lease / failover 相关保护
- 关键 workflow 回归测试
- 兼容 diff 工具或对照脚本
- 基础可观测性补强

## A 线需要冻结的内容

- 关键回归测试集
- 兼容 diff 对照范围
- 风险审计清单
- 必须阻止上线的高风险不兼容项

## B 线实现重点

- 把 hardening 能力落成真正可执行的防护和验证
- 避免只写成文档约定

## 验收 demo

- Demo 1：错误路由或错误 pod 请求被拒绝
- Demo 2：展示 failover 或 lease 失效保护行为
- Demo 3：展示后台任务不会越权处理非本 pod organization
- Demo 4：展示关键测试集合和执行结果

## 待确认项

- 兼容 diff 工具的输入输出形式
- 最低可接受的测试覆盖范围
- 可观测性指标先落日志、指标还是追踪

## 当前不冻结

- 全量生产运维体系
- UI 层诊断工具
- 与 上游参考实现 兼容目标无关的增强功能
