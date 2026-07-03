import { describe, expect, it } from "vitest";
import { runPhaseLabel, runPurposeLabel } from "../utils/runDisplay";

describe("runDisplay", () => {
  it("labels parent issue execution stages without exposing raw wake reasons", () => {
    expect(runPhaseLabel({ contextSnapshot: { wakeReason: "issue_status_changed" }, triggerDetail: "system" })).toBe("任务状态变更后执行");
    expect(runPhaseLabel({ contextSnapshot: { wakeReason: "issue_children_settled" }, triggerDetail: "system" })).toBe("子任务完成后汇总");
    expect(runPurposeLabel({ contextSnapshot: { issueId: "issue-1", wakeReason: "issue_children_settled" }, invocationSource: "assignment", triggerDetail: "system" })).toBe("父任务收尾");
  });
});
