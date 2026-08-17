import type { HeartbeatRun } from "../api/types";
import { sourceLabel } from "./display";

function normalize(value: string | null | undefined): string {
  return value?.trim() ?? "";
}

function triggerDetailLabel(value: string | null | undefined): string | null {
  const normalized = normalize(value);
  return normalized || null;
}

function fallbackReasonLabel(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const normalized = normalize(value);
  return normalized ? sourceLabel(normalized) : null;
}

const RUN_PHASE_LABELS: Record<string, string> = {
  issue_assigned: "任务分配后执行",
  issue_checked_out: "签出后执行",
  issue_children_settled: "子任务完成后汇总",
  issue_comment_added: "评论后继续处理",
  issue_comment_mentioned: "被提及后处理",
  issue_execute: "手动执行",
  issue_passive_followup: "自动收口跟进",
  issue_review_requested: "评审执行",
  issue_status_changed: "任务状态变更后执行",
  issue_changes_requested: "修改请求后执行",
};

export function runPhaseLabel(run: Pick<HeartbeatRun, "contextSnapshot" | "triggerDetail" | "retryOfRunId" | "processLossRetryCount"> | null | undefined): string | null {
  if (!run) return null;
  if (normalize(run.retryOfRunId)) return "恢复重试";
  if ((run.processLossRetryCount ?? 0) > 0) return "进程丢失恢复";
  const reason = runWakeReason(run);
  if (!reason) return null;
  return RUN_PHASE_LABELS[reason] ?? fallbackReasonLabel(reason) ?? reason;
}

export function runContextSnapshot(run: Pick<HeartbeatRun, "contextSnapshot"> | null | undefined): Record<string, unknown> | null {
  const snapshot = run?.contextSnapshot;
  if (!snapshot || typeof snapshot !== "object" || Array.isArray(snapshot)) return null;
  return snapshot as Record<string, unknown>;
}

export function runIssueLabel(run: Pick<HeartbeatRun, "issueIdentifier" | "issueTitle" | "issueId"> | null | undefined): string | null {
  if (!run) return null;
  return normalize(run.issueIdentifier) || normalize(run.issueTitle) || normalize(run.issueId) || null;
}

export function runReasonLabel(run: Pick<HeartbeatRun, "contextSnapshot" | "triggerDetail" | "retryOfRunId" | "processLossRetryCount"> | null | undefined): string | null {
  if (!run) return null;
  if (normalize(run.retryOfRunId)) return `retryOfRunId=${run.retryOfRunId}`;
  if ((run.processLossRetryCount ?? 0) > 0) return `processLossRetryCount=${run.processLossRetryCount}`;
  return (
    fallbackReasonLabel(runContextSnapshot(run)?.wakeReason) ||
    triggerDetailLabel(runContextSnapshot(run)?.wakeReason as string | null | undefined) ||
    fallbackReasonLabel(run.triggerDetail) ||
    triggerDetailLabel(run.triggerDetail)
  );
}

export function runWakeReason(run: Pick<HeartbeatRun, "contextSnapshot" | "triggerDetail"> | null | undefined): string | null {
  if (!run) return null;
  const snapshot = runContextSnapshot(run);
  const wakeReason = snapshot?.wakeReason;
  if (typeof wakeReason === "string" && wakeReason.trim()) return wakeReason.trim();
  if (typeof run.triggerDetail === "string" && run.triggerDetail.trim()) return run.triggerDetail.trim();
  return null;
}

export function isPassiveFollowupRun(run: Pick<HeartbeatRun, "runPurpose" | "contextSnapshot" | "triggerDetail"> | null | undefined): boolean {
  return run?.runPurpose === "closeout_followup" || runWakeReason(run) === "issue_passive_followup";
}

export function runPurpose(run: Pick<HeartbeatRun, "runPurpose" | "invocationSource" | "contextSnapshot" | "triggerDetail"> | null | undefined): NonNullable<HeartbeatRun["runPurpose"]> {
  if (run?.runPurpose) return run.runPurpose;
  if (isPassiveFollowupRun(run)) return "closeout_followup";
  if (run?.invocationSource === "review") return "review";
  if (run?.invocationSource === "timer") return "heartbeat";
  return "task_execution";
}

export function hasIssueContext(run: Pick<HeartbeatRun, "issueId" | "contextSnapshot"> | null | undefined): boolean {
  if (!run) return false;
  if (normalize(run.issueId)) return true;
  const snapshot = runContextSnapshot(run);
  return Boolean(normalize(snapshot?.issueId as string | null | undefined) || normalize(snapshot?.primaryIssueId as string | null | undefined));
}

export function runPurposeLabel(run: Pick<HeartbeatRun, "runPurpose" | "invocationSource" | "contextSnapshot" | "triggerDetail" | "issueId"> | null | undefined): string {
  if (runWakeReason(run) === "issue_children_settled") return "父任务收尾";
  const purpose = runPurpose(run);
  const issueScoped = hasIssueContext(run);
  if (purpose === "closeout_followup") return "自动收口";
  if (purpose === "review") return "评审运行";
  if (purpose === "heartbeat") {
    if (run?.invocationSource === "timer") return "心跳";
    if (run?.invocationSource === "on_demand") return "运行诊断";
    return issueScoped ? "任务运行" : "无任务运行";
  }
  return issueScoped ? "任务执行" : "运行诊断";
}

export function isTaskExecutionRun(run: Pick<HeartbeatRun, "runPurpose" | "invocationSource" | "contextSnapshot" | "triggerDetail"> | null | undefined): boolean {
  return runPurpose(run) === "task_execution";
}

export function runDescriptor(run: HeartbeatRun | null | undefined): string {
  if (!run) return "-";
  const parts: string[] = [];
  const source = normalize(run.invocationSource);
  if (source) parts.push(source);
  const reason = runReasonLabel(run);
  if (reason && reason !== source) parts.push(reason);
  return parts.length > 0 ? parts.join(" · ") : "-";
}
