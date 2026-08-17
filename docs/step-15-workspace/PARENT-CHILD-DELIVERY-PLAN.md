# 父子任务交付优化计划

## 背景

本文定义 Octopus 如何支持一个主任务创建真实子任务、等待子任务产出，并由主任务自己完成最终汇总交付。

典型场景：

```text
介绍一下四大美女。每个美女创建一个子任务分别介绍。所有子任务完成后，主任务汇总结果，给我一个最终报告。
```

产品边界：

- 平台不应该自动把子任务产物合并成主任务报告。
- 主任务是 manager，负责拆分子任务、检查子任务结果、判断质量、生成最终报告。
- 平台负责状态机、调度、work products 追溯、最终交付物可见性和 closeout 约束；共享工作区下不替用户做物理目录隔离。

## 当前支持情况

Octopus 已经具备主干机制：

- issue 支持 `parentId`，子任务是真实 board issue，不是 runtime 内部 todo。
- 子任务会继承父任务的 project 和 workspace preference。
- runtime prompt 已要求产品可见的拆分工作必须创建真实 Octopus child issue。
- 父任务在子任务仍 open 时不能 `done`。
- 父任务可以进入 `waiting_for_children`。
- 子任务进入 `done`、`blocked`、`cancelled` 后，平台会检查父任务下是否仍有 active child。
- 如果没有 active child，平台会用 `wakeReason=issue_children_settled` 唤醒父任务。
- 每个 issue 都可以持久化自己的 work products。
- 父任务可以通过现有 issue API 查询子任务和子任务 work products。

当前已能跑通的基础链路是：

```text
主任务创建子任务 -> 子任务执行 -> 子任务收尾 -> 平台唤醒主任务 -> 主任务可以汇总
```

### 升级与旧数据恢复

父任务 continuation 以父任务下全部子项的结算代次作为幂等依据。同一轮多个子项并发收尾只创建一个 continuation；任一子项重新打开并再次结算后，才进入新一轮。父 Issue 行锁负责串行判断“最后一个活动子项已经结束”，避免 PostgreSQL 并发事务同时跳过唤醒。

升级前已经漏掉 continuation、仍停在 `todo` 或 `in_progress` 的父任务不会被自动改写状态：

- Agent 处于 active 且 Heartbeat 已启用时，下一次 Heartbeat 预检会发现该父任务；也可以点击“立即唤醒”提前检查。
- Agent 已暂停时，先恢复 Agent，再点击“立即唤醒”。
- Heartbeat 已禁用时，使用“立即唤醒”手动恢复。
- 父任务没有 assignee 时，先分配 Agent，再执行唤醒。

## 不完善的地方

当前还不能算一个足够稳的 manager workflow：

- 父任务 resume 上下文已补强。`issue_children_settled` 唤醒时会注入 child primary work products，并且可通过聚合 API/CLI 拉取 child 状态、closeout 摘要和 work products。
- 父任务不再需要多次低层查询；manager agent 可以使用 `octopus issue children <parent-id> --include-work-products --json` 一次收集子任务输出。
- 当 wake reason 是 `issue_children_settled` 时，父任务 prompt 已明确要求基于 child primary work products 生成父任务自己的最终交付。
- 平台已经阻止“有 open child 时 done”，并在父任务 done 缺少子任务结果使用证据时记录 soft warning；UI / run history 已展示 children settled 和 convergence warning。
- runtime 产物路径必须稳定可写。共享工作区下，报告和项目文件都可以写入共享现场或用户指定路径；issue work products 负责记录来源，不代表物理隔离。
- closeout governance 不能允许 issue run 或 passive followup 在没有成功执行 `octopus issue done/block/comment` 时表现为成功。
- UI 对父子任务产物关系、等待原因、唤醒原因的展示还不够清楚。

## 产品模型

需要区分两个概念：执行环境和交付可见性。

执行环境回答：

```text
agent 在哪里跑？
是否共享项目上下文？
是否可能和其他任务写文件冲突？
```

交付可见性回答：

```text
用户第一眼应该看到什么？
哪些文件只是执行证据或来源材料？
Octopus 怎么追溯哪个 run / issue / agent 写过它？
```

对于“四大美女”这类拆分写报告再汇总的任务，推荐默认模型是：

```text
共享 workspace + 共享文件现场 + work product 元数据追溯 + 父任务 primary deliverable
```

也就是：子任务可以在共享工作区中写约定的共享路径，例如：

```text
reports/four-beauties/xi-shi.md
reports/four-beauties/wang-zhaojun.md
reports/four-beauties/diao-chan.md
reports/four-beauties/yang-guifei.md
reports/four-beauties.md
```

平台不通过每个 child issue 的物理目录来避免覆盖。共享工作区的语义就是共享现场；覆盖风险由用户/agent 的路径约定、diff review 和 closeout 控制。Octopus 通过 work product 元数据记录 `issueId`、`runId`、`agentId`、路径、时间和摘要，用于追溯和 UI 展示。

## 交付模式

用户不应该每次手写复杂 path policy。Octopus 应提供简单交付模式，并自动推断默认行为。

### 任务输出

默认登记模式。

适用于用户要求报告、分析、总结、对比、计划、截图、CSV 等交付，但没有明确说要写进项目文档或代码仓库。

默认行为：

- 在 shared workspace 下，输出可以写入共享工作区或 organization artifacts 中的约定路径，不强制每个 child issue 一个物理目录。
- 在 isolated workspace 下，输出可以写入当前 issue worktree 或 organization artifacts。
- 在 operator branch 下，输出可以写入固定 operator worktree 或 organization artifacts。
- 无论物理路径在哪里，都登记为 issue work products，并记录 `issueId`、`createdByRunId`、`executionWorkspaceId` 和路径。
- 主任务最终报告必须登记为父任务的 primary deliverable，UI 默认置顶展示。

### 项目文档

当用户明确说“写到项目文档、docs、仓库、指定项目路径”时使用。

典型输出位置：

```text
docs/<requested-document>.md
```

行为：

- 视为项目变更。
- 需要限制到允许的项目路径。
- closeout 需要说明变更路径。
- work product 可以引用这个文件，但项目文件本身是 source of truth。

### 代码变更

当用户要求实现功能、修改行为或修 bug 时使用。

行为：

- 写项目源码文件。
- 需要冲突处理、git policy、测试和 review 预期。
- 父子任务并行改代码时必须特别小心重叠文件冲突。

## 父任务重新执行语义

重新执行不是从空白任务重新开始，也不是机械地只处理异常子任务。重新执行应在当前 issue 树和历史产物基础上，由 manager agent 重新判断最合适的执行策略。

平台必须给 agent 提供完整事实：

- 父任务当前标题、描述、状态、最近 run 结果和 closeout 记录。
- 现有 child issues，按 `parentId` 查询，不引入额外 `childKey` 身份层。
- 每个 child 的状态、负责人、最近 closeout/comment、work products、失败原因和产物缺失情况。
- 父任务已有 work products 和最终交付物状态。

agent 可以选择：

- 复用已有 done child 的产物并继续汇总。
- 重试 blocked、failed、timed out 或 process lost 的 child issue。
- 接管某个 child 的缺失工作，在父任务中补产物，并记录来源说明。
- 追加新的 child issue，补足原任务树缺少的工作。
- 替换旧 child issue，但必须 comment/activity 说明替代关系和旧 child 的处理原因。
- 取消不再需要的旧 child issue，并说明为什么不再需要。
- 在原拆分明显不合理时重新拆分，但必须先显式处置已有 children，不能直接重复创建一批同类子任务。
- 如果不需要拆分或继续拆分，在父任务内直接完成。

硬约束：

- 不能忽略已有 children，把重新执行当成第一次执行。
- 不能因为旧 child blocked 或没有产物，就静默创建同名 sibling 规避问题。
- 父任务 closeout 前必须说明已有 children 是被复用、等待、重试、替换、取消、接管，还是被纳入重新拆分。
- 有 active child 时，父任务不能 `done`。
- 有 blocked/cancelled child 且用户没有接受不完整交付时，父任务不能把结果当完整成功。

当前模型不新增 `childKey` 或计划表。父子关系由 `issues.parent_id` 表达，child issue 自身的 `issue.id` 就是执行事实身份。只有未来需要“先审批计划再创建 issue”、“一个计划项绑定多个 replacement issue”、“计划版本 diff/回滚”等能力时，才考虑引入独立 plan item 表。

## 优化计划

### 1. 强化父任务 Resume / Rerun Reconcile 上下文

当父任务以 `wakeReason=issue_children_settled` 被唤醒，或用户/API 重新执行已有父任务时，向 runtime context 和 prompt 注入面向 manager 的子任务摘要与重新执行事实。

每个 child 应包含：

- identifier 和 title。
- status。
- assignee。
- 最后 closeout/comment 摘要。
- work products：title、type、content path、可用时的内容摘要。
- 子任务是 done、active、blocked、cancelled，还是缺少期望产物。
- 旧 run 是否 failed、timed out、process lost，以及对应错误摘要。

目标：主任务醒来或重新执行后直接知道该检查什么、汇总什么、恢复什么，而不是把已有 issue 树当成空白任务重新开始。

### 2. 新增 Child Outputs 聚合命令

增加一个一次性返回子任务及产物的 control-plane 命令。

已实现命令：

```text
octopus issue children <parent-id> --include-work-products --json
```

对应 API：

```text
GET /api/issues/{id}/children?includeWorkProducts=true
```

返回内容：

- parent issue 摘要。
- child issue 列表。
- child status 和 closeout 信息。
- child work products。
- active child 数量和 settled child 数量。

目标：manager agent 不需要多次低层调用才能收集子任务输出。

### 3. 改进父任务 Manager Prompt

当 issue 有 child issues、wake reason 是 `issue_children_settled`，或本次 run 是重新执行时，增加明确指令：

- 父任务 closeout 前必须检查所有 child issue 结果。
- blocked/cancelled child 需要作为异常输入说明，不能当成功内容处理。
- 最终报告应基于 child outputs，而不是只凭记忆重写。
- 如果 child outputs 不完整或质量不足，应 comment 下一步、重试原 child、接管补产物、创建明确补充/替换 child，或在用户接受后交付不完整结果。
- 只有在产出主任务要求的最终交付后，才能 `done`。
- 重新执行时必须先审视已有 children；可以重新拆分或追加，但必须说明旧 children 如何处置，不能无视已有 children 重复创建同类任务。

目标：让主任务像 manager 一样收尾和恢复执行，而不是像普通单任务 worker 一样随便醒来后 closeout，也不是把重新执行当成第一次执行。

### 4. 增加父任务 Closeout 软校验

保留现有硬约束：有 active child 时父任务不能 `done`。

增加软 warning：当有 child issues 的父任务 closeout 时，检查是否有使用子任务结果的证据。当前已在 heartbeat closeout governance 中记录 `issue.parent_deliverable_convergence_warning`，不硬失败。

可选信号：

- done comment 提到所有 child identifier 或 title。
- 父任务最终 work product 创建时间晚于所有 child settle 时间。
- 父任务 run 调用了 child outputs 聚合接口或读取了 child work products。

先记录 activity/warning，不做硬失败。

目标：发现“父任务没有真正汇总子任务”的坏结果，同时避免流程过硬导致误伤。

### 5. 稳定共享输出和追溯路径

shared workspace 下，不再把 `artifacts/issues/<issue-id>/` 定义为默认隔离路径。任务可以写共享工作区中的约定路径，例如 `reports/`、`docs/` 或用户指定文件；平台用 work product metadata 追溯来源。

兼容的 `OCTOPUS_ISSUE_ARTIFACTS_DIR` 仍可保留，作为“把当前 issue 的输出放到一个建议目录”的便利入口，但它不是 shared 模式的隔离模型，也不是用户必须理解的产品概念。

目标：Octopus 推荐给 agent 的路径必须与 workspace mode 语义一致：shared 是共享现场，isolated 才是任务级工作区隔离，operator branch 是长期分支协作。

### 6. 强化 Closeout Governance

issue run 只有留下真实 control-plane closeout 信号，才可以视为完整成功。

规则：

- 任务执行没有 `issue done`、`issue block` 或 `issue comment` 时，应标记为 `closeout_missing`。
- passive followup 如果没有执行真实 closeout command，也应 `closeout_missing`，不能伪成功。
- passive followup 不应作为缺失 closeout 的无限重试替代品。

目标：父子任务链路不能看起来成功，实际上没有交付或没有收尾。

### 7. 增加端到端验收用例

已用“四大美女”作为 manager-subtask-closeout 契约验收场景：

1. 主任务被派发。
2. 主任务创建 4 个 child issues。
3. 主任务 comment 进展并退出。
4. 主任务进入 `waiting_for_children`。
5. 每个 child 在共享约定路径或 artifacts 中生成自己的报告，并登记为各自 work product 后 `done`。
6. 最后一个 child settle 后，平台用 `issue_children_settled` 唤醒主任务。
7. 主任务读取 child outputs，生成最终汇总报告，并标记为父任务 primary deliverable。
8. 主任务 `done`。
9. 主任务详情展示最终 work product 和 child issue 关系。

目标：把 manager-subtask-closeout 链路固定成回归测试。

### 8. 改进 UI 可见性

父任务详情页应展示：

- child issue 状态汇总。
- child work product 入口。
- 父任务是否正在 waiting for children。
- 父任务为何被唤醒：children settled。
- 主任务最终产物与子任务产物分开展示。

run history 应展示：

- `issue_children_settled` 是父任务 continuation。
- 哪个 child settle 触发了最终唤醒。
- `closeout_missing` 错误需要明显展示。

目标：用户能看懂主任务为什么等待、为什么醒、汇总用了哪些子任务结果。

## 验收标准

“四大美女”场景达到以下表现时，可认为链路打磨完成：

- 主任务创建 4 个真实 child issues。
- 主任务创建 delegated child 后不在本 run 内代做子任务内容。
- 子任务在共享约定路径或 artifacts 中生成报告；不要求 shared workspace 下每个 child 有物理隔离目录。
- 子任务报告被捕获为各自 work products。
- 任一 child active 时，父任务不能 close done。
- 所有 children settle 后，父任务自动被唤醒。
- 父任务能收到或一键拉取 compact child outputs summary。
- 父任务最终报告登记为父任务 primary deliverable，UI 第一眼展示；物理路径可以是共享约定路径或 artifacts。
- 最终报告被捕获为父任务 work product。
- 父任务通过真实 `octopus issue done` 收尾。
- 没有真实 closeout 信号的 issue run 或 followup 不能显示为成功。
- 重新执行已有 children 的父任务时，runtime context 展示现有 children、状态、产物和异常；agent 不能无视这些事实直接重复创建同类子任务。
- 重新执行时如需重新拆分、追加或替换子任务，必须对旧 child issue 留下 comment/activity 说明处置关系。
- done 但缺少期望产物、blocked、failed、process lost 的 child issue 必须在父任务 closeout 前被重试、接管、替换、取消或作为用户接受的不完整交付记录下来。

## 非目标

- 平台不自动替父任务写最终报告。
- 平台不自动读取并改写子任务报告来判断内容质量。
- 平台不强制所有报告写进项目 docs。
- 平台不把复杂 deliverables JSON 暴露成默认用户体验。
- 当共享上下文有价值时，平台不默认强迫所有子任务使用独立 workspace。

## 推荐默认值

普通 delegated report work：

```text
执行环境：shared workspace
文件语义：共享现场，路径由用户/agent 约定
child 输出：登记为 child issue work products
parent 输出：登记为 parent primary deliverable，UI 置顶展示
```

明确项目文档交付：

```text
执行环境：shared workspace 或受控 project workspace
输出归属：project document
路径：docs/<requested-name>.md
```

代码实现任务：

```text
执行环境：有锁/git policy 的 shared workspace，或 isolated workspace
输出归属：code change
closeout：必须说明测试和变更文件
```
