# 父子任务收尾策略实施说明

状态：实施中

## 目标

父任务拆分子任务时必须持久化本批次的收尾策略。策略只描述业务要求，不直接改变
Run 状态，也不能代替终态副作用。当前批次仍由 `parent_id + origin_run_id` 标识，
不增加批次业务表。

## 数据契约

子任务在 `issues.closeout_policy` 保存同一份 JSON：

```json
{"version": 1, "mode": "child_outputs_are_final"}
```

或：

```json
{
  "version": 1,
  "mode": "parent_output_required",
  "requirements": {
    "minimumOutputs": 1,
    "primaryOutputRequired": true
  }
}
```

UI 只显示“子任务产出即完成”或“父任务还需产出”，不暴露内部枚举或原始 JSON。

## 两条收尾路径

### 子任务产出即完成

最后一个子任务进入终态后，系统按当前批次检查：

1. 没有仍在执行或评审的子任务；
2. 被阻塞或取消的子任务已由人工通过 `issue.incomplete_accepted` 明确接受；
3. 每个已完成子任务都有主产物。

全部通过后，系统直接完成父任务，不创建父任务 Agent Run。验证失败时父任务进入
`blocked`，活动记录给出缺失的子任务或产物。

### 父任务还需产出

最后一个子任务进入终态后，系统创建父任务 continuation Run。Agent 调用
`octopus issue done` 时只记录 `issue.closeout_requested`，父任务保持
`in_progress`。该活动记录当前 Run、委派来源 Run、完成说明和声明的产物路径；子任务
ID 由系统按批次查询，不由 Agent 提交。

Adapter 结束并把实际产物落库后，`RunFinalizationService` 校验结构化请求与真实主
产物。校验通过才把父任务改为 `done`（有 reviewer 时改为 `in_review`）；校验失败
则 Run 为 `failed/closeout_missing`，父任务仍为 `in_progress`。错误必须指出缺少的是
收尾请求、主产物声明、实际产物还是未结束的子任务。

## 服务边界

- `RunDispatchService`：领取排队 Run，并交给一次性的执行服务。
- `RunExecutionService`：管理一个 Run、Adapter、数据库 Session 和租约生命周期。
- `RunFinalizationService`：执行 Run 终态 CAS、收尾策略验证和幂等终态副作用。
- `RunRecoveryService`：扫描异常 Run，并通过同一终态副作用入口幂等重放。
- `ParentContinuationCoordinator`：只判断当前批次是否全部 settled，并选择自动收尾或父任务 continuation。
- `ParentCloseoutGovernance`：封装收尾请求、批次状态和产物证据验证。

`RunRecoveryService` 不直接调用 Adapter；需要重试时创建关联原 Run 的新 Run，再交给
`RunDispatchService`。

## CLI

- 默认：`octopus issue create-children <parent> --children-file <children.json>`
- 要求父任务产出：增加 `--parent-output-required`
- 高级策略：使用 `--closeout-policy-file <policy.json>`，不接受行内策略 JSON
- 多行完成说明：`octopus issue done <issue> --comment-file <comment.md>`

当前唤醒评论或指令决定本次创建批次采用哪种策略；原始 Issue 描述只作为背景，不能
覆盖当前指令。

## 恢复与幂等

Run 终态与 `terminal_effects_pending` 仍由同一原子 CAS 写入。父任务收尾属于终态
副作用：活动写入按 Run 与委派来源去重，`RunRecoveryService` 可以安全重放，重复
执行不能再次完成任务、重复创建 continuation 或重复唤醒 reviewer。

## 验收场景

1. 默认批次的所有子任务有主产物：父任务自动完成，没有父任务 Run。
2. 默认批次缺少子任务主产物：父任务阻塞，错误指出具体子任务。
3. 父任务产出策略提交有效声明且产物存在：请求时不完成，Adapter 结束后完成。
4. 父任务产出策略缺少请求、声明或实际产物：Run 失败，Issue 保持进行中。
5. 已存在的父任务主产物只有在当前 Run 重新明确声明时才可作为证据。
6. 多行 `--comment-file` 完整保留 Markdown。
7. terminal effects 重放不产生重复活动、Run 或唤醒。
