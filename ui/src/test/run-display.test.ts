import { describe, expect, it } from "vitest";
import { runPhaseLabel, runPurposeLabel, runStatusLabel, runTerminalReasonLabel } from "../utils/runDisplay";

describe("runDisplay", () => {
  it("labels parent issue execution stages without exposing raw wake reasons", () => {
    expect(runPhaseLabel({ contextSnapshot: { wakeReason: "issue_status_changed" }, triggerDetail: "system" })).toBe("任务状态变更后执行");
    expect(runPhaseLabel({ contextSnapshot: { wakeReason: "issue_children_settled" }, triggerDetail: "system" })).toBe("子任务完成后汇总");
    expect(runPurposeLabel({ contextSnapshot: { issueId: "issue-1", wakeReason: "issue_children_settled" }, invocationSource: "assignment", triggerDetail: "system" })).toBe("父任务收尾");
  });

  it("explains review runs superseded by a durable review decision", () => {
    expect(runStatusLabel({ status: "cancelled", errorCode: "review_resolved_by_human" })).toBe("评审已由人工完成");
    expect(runTerminalReasonLabel({ errorCode: "review_superseded_by_another_run" })).toBe("已被其他评审结论替代");
    expect(runStatusLabel({ status: "cancelled", errorCode: "cancelled" })).toBe("已取消");
  });
});
