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

export function runIssueLabel(run: Pick<HeartbeatRun, "issueIdentifier" | "issueTitle" | "issueId"> | null | undefined): string | null {
  if (!run) return null;
  return normalize(run.issueIdentifier) || normalize(run.issueTitle) || normalize(run.issueId) || null;
}

export function runReasonLabel(run: Pick<HeartbeatRun, "contextSnapshot" | "triggerDetail" | "retryOfRunId" | "processLossRetryCount"> | null | undefined): string | null {
  if (!run) return null;
  if (normalize(run.retryOfRunId)) return `retryOfRunId=${run.retryOfRunId}`;
  if ((run.processLossRetryCount ?? 0) > 0) return `processLossRetryCount=${run.processLossRetryCount}`;
  return (
    fallbackReasonLabel((run.contextSnapshot as Record<string, unknown> | null | undefined)?.wakeReason) ||
    triggerDetailLabel((run.contextSnapshot as Record<string, unknown> | null | undefined)?.wakeReason as string | null | undefined) ||
    fallbackReasonLabel(run.triggerDetail) ||
    triggerDetailLabel(run.triggerDetail)
  );
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
