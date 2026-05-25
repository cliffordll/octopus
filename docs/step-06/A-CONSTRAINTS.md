# Step 6 A Constraints

## 当前状态

当前文件是草稿版本。

用途是先给出 Step 6 的 read API 方向，不作为当前阶段的冻结实现约束。等 B 完成 Step 3 后，再根据 shared contract 和 database mapping 的实际产物细化字段级约束。

## 目标

优先实现只读接口，尽早暴露 Octopus 与 上游参考实现 在字段、nullability、排序、过滤行为上的差异。

## 本阶段范围

- 第一批 `orgs` 读取接口
- 第一批 `issues` 读取接口
- 第一批 `approvals` 读取接口
- 对应 contract test / response assertion

## A 线必须先冻结的内容

- 以下内容暂不视为已冻结，只是后续收口方向：
- 第一批读接口的响应字段清单
- nullability 和默认值语义
- 排序、过滤、identifier 解析等读语义
- 上游参考实现 侧对照样本

## B 线实现边界

- 先打通 route -> service -> query -> shared contract 的完整读取链路
- 不在 read API 阶段混入 mutation 逻辑

## 验收 demo

- Demo 1：调用 1 到 2 个只读接口并展示返回结果
- Demo 2：逐字段对照 上游参考实现 返回结构
- Demo 3：展示 read contract 测试结果
- Demo 4：说明 route、service、query、shared contract 的协作关系

## 待确认项

- 第一批验收是否先以 `orgs` / `issues` 为主，`approvals` 后补
- 详情接口中的聚合字段由哪一层提供
- 是否保留 上游参考实现 当前的宽松 / 严格空值行为

## Step 3 完成后再补

- 第一批真实落地的 request / response types 对应哪些字段
- route、service、query 三层各自负责哪些聚合字段
- `GET /api/issues` 错误入口的最终兼容实现口径
- 首批 read contract test 样例

## 当前不冻结

- chat 读取接口
- 大量辅助列表接口
- 非第一批统计与 dashboard 接口
