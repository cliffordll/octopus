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

function runContextSnapshot(run: Pick<HeartbeatRun, "contextSnapshot"> | null | undefined): Record<string, unknown> | null {
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

export function runPurposeLabel(run: Pick<HeartbeatRun, "runPurpose" | "invocationSource" | "contextSnapshot" | "triggerDetail"> | null | undefined): string {
  const purpose = runPurpose(run);
  if (purpose === "closeout_followup") return "收尾跟进";
  if (purpose === "review") return "评审";
  if (purpose === "heartbeat") return "心跳";
  return "任务执行";
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
