import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { useEffect, useRef, useState, type ChangeEvent, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { activityApi } from "../api/activity";
import { agentsApi } from "../api/agents";
import { goalsApi } from "../api/goals";
import { heartbeatApi } from "../api/heartbeat";
import { issuesApi } from "../api/issues";
import { projectsApi } from "../api/projects";
import type {
  Agent,
  ActivityEvent,
  Goal,
  HeartbeatRun,
  HeartbeatRunEvent,
  IssueComment,
  IssueDetail,
  IssueListItem,
  IssuePriority,
  IssueReviewDecision,
  IssueStatus,
  IssueWorkProduct,
  LogReadResult,
  ProjectDetail,
  UpdateIssuePayload,
  WorkspaceOperation,
} from "../api/types";
import { Badge } from "../components/Badge";
import { IssuesWorkspace } from "../components/ContextWorkspace";
import { ErrorNotice } from "../components/ErrorNotice";
import { StatusPill } from "../components/StatusPill";
import { formatBytes, formatDateTime, formatMoneyCents, priorityLabel, runErrorMessage, sourceLabel, statusLabel } from "../utils/display";
import { isPassiveFollowupRun, isTaskExecutionRun, runDescriptor, runIssueLabel, runPurposeLabel, runWakeReason } from "../utils/runDisplay";
import { writeRecentIssue } from "../utils/recentIssues";

const ISSUE_STATUSES: IssueStatus[] = ["backlog", "todo", "in_progress", "in_review", "done", "blocked", "cancelled"];
const ISSUE_PRIORITIES: IssuePriority[] = ["critical", "high", "medium", "low"];
const LIVE_RUN_REFETCH_MS = 1000;
const AGENT_REPLY_COLLAPSE_CHARS = 600;
const AGENT_REPLY_COLLAPSE_LINES = 8;
const RUN_SUMMARY_PREVIEW_CHARS = 110;

interface RunStreamCursor {
  lastSeq: number;
  nextOffset: number;
}

function issueDisplayId(issue: IssueDetail): string {
  return issue.identifier ?? issue.id.slice(0, 8);
}

function nullableSelectValue(value: string | null | undefined): string {
  return value ?? "";
}

function agentName(agentId: string | null | undefined, agentsById: Map<string, Agent>): string {
  if (!agentId) return "-";
  return agentsById.get(agentId)?.name ?? agentId;
}

function agentMentionToken(agent: Agent): string {
  const candidates = [agent.urlKey, agent.name, agent.id];
  for (const candidate of candidates) {
    if (typeof candidate === "string" && /^[A-Za-z0-9][A-Za-z0-9_.-]*$/.test(candidate)) return candidate;
  }
  return agent.id;
}

function mentionQueryAtCursor(value: string, cursor: number): { start: number; query: string } | null {
  const prefix = value.slice(0, cursor);
  const match = /(^|\s)@([A-Za-z0-9_.-]*)$/.exec(prefix);
  if (!match) return null;
  return { start: prefix.length - match[2].length - 1, query: match[2].toLowerCase() };
}

function issueRunStorageKey(orgId: string, issueId: string): string {
  return `octopus:issue-run:${orgId}:${issueId}`;
}

function reviewDecisionBlockReason(issue: IssueDetail): string {
  if (!issue.reviewerAgentId) return "请先设置 Reviewer，当前任务不能评审。";
  if (!["in_review", "blocked"].includes(issue.status)) return "任务进入 in_review 或 blocked 后才能评审。";
  return "";
}

function reviewDecisionLabel(decision: IssueReviewDecision): string {
  switch (decision) {
    case "approve":
      return "通过评审";
    case "request_changes":
      return "请求修改";
    case "needs_followup":
      return "需要人工处理";
    case "blocked":
      return "标记阻塞";
  }
}

function reviewStatusText(issue: IssueDetail, agentsById: Map<string, Agent>): string {
  if (!["in_review", "blocked"].includes(issue.status)) return "当前任务不在评审阶段。";
  if (!issue.reviewerAgentId) return "未设置 Reviewer，无法提交评审结论。";
  const reviewer = agentName(issue.reviewerAgentId, agentsById);
  return issue.status === "blocked"
    ? `任务已阻塞，等待 ${reviewer} 给出 closeout 或后续处理意见。`
    : `任务正在评审中，等待 ${reviewer} 给出 closeout。`;
}

function markReviewBlockReason(issue: IssueDetail): string {
  if (!issue.reviewerAgentId) return "请先设置 Reviewer，当前任务不能标记为待评审。";
  if (issue.status === "in_review") return "当前任务已经是待评审状态。";
  return "";
}

function isLiveRun(status?: string | null): boolean {
  return status === "queued" || status === "running";
}

function isOpenIssueStatus(status?: string | null): boolean {
  return status === "todo" || status === "in_progress" || status === "in_review" || status === "blocked";
}

function isRerunnableRun(status?: string | null): boolean {
  return status === "failed" || status === "timed_out" || status === "cancelled";
}

function isTerminalRun(status?: string | null): boolean {
  return status === "succeeded" || isRerunnableRun(status);
}

function heartbeatRunId(run: HeartbeatRun | null | undefined): string {
  return run?.id || run?.runId || "";
}

function runContextIssueId(run: HeartbeatRun | null | undefined): string | null {
  const value = run?.contextSnapshot?.issueId ?? run?.contextSnapshot?.primaryIssueId;
  return typeof value === "string" && value ? value : null;
}

function runBelongsToIssue(run: HeartbeatRun | null | undefined, issueId: string, listedRunIds: Set<string>): boolean {
  if (!run) return false;
  const runId = heartbeatRunId(run);
  if (runId && listedRunIds.has(runId)) return true;
  return run.issueId === issueId || runContextIssueId(run) === issueId;
}

function runSortTime(run: HeartbeatRun): number {
  const value = run.createdAt ?? run.startedAt ?? run.updatedAt ?? "";
  const time = Date.parse(value);
  return Number.isNaN(time) ? 0 : time;
}

function activeQueueRunsForAgent(runs: HeartbeatRun[], agentId: string | null | undefined): HeartbeatRun[] {
  if (!agentId) return [];
  return runs
    .filter((run) => run.agentId === agentId && isLiveRun(run.status))
    .sort((left, right) => runSortTime(left) - runSortTime(right));
}

function queueRunsAhead(activeRuns: HeartbeatRun[], currentRun: HeartbeatRun | null): number {
  if (!currentRun) return 0;
  const currentRunId = heartbeatRunId(currentRun);
  const currentIndex = activeRuns.findIndex((run) => heartbeatRunId(run) === currentRunId);
  if (currentIndex >= 0) return currentIndex;
  const currentTime = runSortTime(currentRun);
  return activeRuns.filter((run) => runSortTime(run) <= currentTime).length;
}

function queueSourceCounts(runs: HeartbeatRun[]): Array<{ count: number; source: string }> {
  const counts = new Map<string, number>();
  for (const run of runs) counts.set(run.invocationSource, (counts.get(run.invocationSource) ?? 0) + 1);
  return Array.from(counts.entries())
    .map(([source, count]) => ({ count, source }))
    .sort((left, right) => right.count - left.count || sourceLabel(left.source).localeCompare(sourceLabel(right.source)));
}

function latestIssueRun(runs: HeartbeatRun[], currentRun: HeartbeatRun | null, issueId: string): HeartbeatRun | null {
  const merged = new Map<string, HeartbeatRun>();
  const listedRunIds = new Set<string>();
  for (const run of runs) {
    const id = heartbeatRunId(run);
    if (id) {
      listedRunIds.add(id);
      merged.set(id, run);
    }
  }
  if (currentRun && runBelongsToIssue(currentRun, issueId, listedRunIds)) {
    const id = heartbeatRunId(currentRun);
    if (id) {
      const listedRun = merged.get(id);
      merged.set(id, listedRun ? { ...listedRun, ...currentRun } : currentRun);
    }
  }
  const sorted = Array.from(merged.values())
    .filter(isTaskExecutionRun)
    .sort((left, right) => runSortTime(right) - runSortTime(left));
  return sorted[0] ?? null;
}

function latestTerminalRunForIssue(runs: HeartbeatRun[], issueId: string): HeartbeatRun | null {
  const listedRunIds = new Set(runs.map(heartbeatRunId).filter(Boolean));
  const sorted = runs
    .filter((run) => isTerminalRun(run.status) && runBelongsToIssue(run, issueId, listedRunIds))
    .sort((left, right) => runSortTime(right) - runSortTime(left));
  return sorted[0] ?? null;
}

function latestAnyRunForIssue(runs: HeartbeatRun[], issueId: string): HeartbeatRun | null {
  const listedRunIds = new Set(runs.map(heartbeatRunId).filter(Boolean));
  const sorted = runs
    .filter((run) => runBelongsToIssue(run, issueId, listedRunIds))
    .sort((left, right) => runSortTime(right) - runSortTime(left));
  return sorted[0] ?? null;
}

function metadataText(metadata: Record<string, unknown> | null | undefined, key: string): string {
  const value = metadata?.[key];
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

function nextLogOffset(log: LogReadResult): number | null {
  if (typeof log.nextOffset === "number") return log.nextOffset;
  if (typeof log.endOffset === "number") return log.endOffset;
  return null;
}

function AutoScrollPre({
  className,
  content,
}: {
  className: string;
  content: string;
}) {
  const ref = useRef<HTMLPreElement | null>(null);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    node.scrollTop = node.scrollHeight;
  }, [content]);
  return <pre className={className} ref={ref}>{content}</pre>;
}

function streamLogDelta(streamLog: string, persistedLog: string | undefined): string {
  if (!streamLog) return "";
  const persisted = persistedLog ?? "";
  if (!persisted) return streamLog;
  if (persisted.includes(streamLog)) return "";
  if (streamLog.startsWith(persisted)) return streamLog.slice(persisted.length);
  return streamLog;
}

function runElapsedText(run: HeartbeatRun | null): string {
  const startedAt = run?.startedAt ?? run?.createdAt;
  if (!startedAt) return "";
  const startedTime = Date.parse(startedAt);
  if (Number.isNaN(startedTime)) return "";
  const endTime = run?.finishedAt ? Date.parse(run.finishedAt) : Date.now();
  if (Number.isNaN(endTime) || endTime <= startedTime) return "";
  const elapsedSeconds = Math.floor((endTime - startedTime) / 1000);
  if (elapsedSeconds < 60) return `${elapsedSeconds} 秒`;
  const minutes = Math.floor(elapsedSeconds / 60);
  const seconds = elapsedSeconds % 60;
  if (minutes < 60) return seconds ? `${minutes} 分 ${seconds} 秒` : `${minutes} 分`;
  const hours = Math.floor(minutes / 60);
  const restMinutes = minutes % 60;
  return restMinutes ? `${hours} 小时 ${restMinutes} 分` : `${hours} 小时`;
}

function metadataString(metadata: Record<string, unknown> | null | undefined, key: string): string | null {
  const value = metadata?.[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function pathBasename(value: string | null | undefined): string {
  if (!value?.trim()) return "";
  const normalized = value.replace(/\\/g, "/");
  const parts = normalized.split("/").filter(Boolean);
  return parts.at(-1) ?? value;
}

function workProductDisplayName(product: IssueWorkProduct): string {
  return (
    pathBasename(product.title) ||
    pathBasename(metadataString(product.metadata, "workspacePath")) ||
    pathBasename(product.externalId) ||
    product.id
  );
}

function workProductSourceLabel(product: IssueWorkProduct): string {
  const source = metadataString(product.metadata, "source") ?? "";
  const workspacePath = metadataString(product.metadata, "workspacePath") ?? "";
  const browserPath = metadataString(product.metadata, "workspaceBrowserPath") ?? "";
  const combinedPath = `${workspacePath}/${browserPath}`;
  if (source.includes("run") || combinedPath.includes("/runs/") || combinedPath.includes("\\runs\\")) return "运行产物";
  if (source.includes("execution_workspace")) return "工作区产物";
  if (source.includes("organization_artifacts")) return "任务产物";
  if (product.createdByRunId) return "运行产物";
  return "任务产物";
}

function activitySummary(event: ActivityEvent): string {
  if (event.action === "issue.closure_needs_operator_review") return issueCloseoutReviewSummary(event);
  if (event.action === "issue.review_closeout_missing") return issueCloseoutReviewSummary(event);
  if (event.action === "issue.convergence_review_requested") return issueConvergenceReviewSummary(event);
  if (typeof event.summary === "string" && event.summary.trim()) return event.summary;
  const details = event.details ?? {};
  for (const key of ["summary", "message", "title", "note"]) {
    const value = details[key];
    if (typeof value === "string" && value.trim()) return value;
  }
  return event.entityId;
}

function activityTitle(event: ActivityEvent): string {
  switch (event.action) {
    case "issue.executed":
      return "执行任务";
    case "issue.status_changed":
      return "状态变更";
    case "issue.created":
      return "创建任务";
    case "issue.updated":
      return "更新任务";
    case "issue.reviewed":
      return "评审任务";
    case "issue.closure_needs_operator_review":
      return "需要人工确认收口";
    case "issue.review_closeout_missing":
      return "缺少评审结论";
    case "issue.convergence_review_requested":
      return "需要收敛评审";
    case "heartbeat.invoked":
      return "唤醒智能体";
    case "heartbeat.retried":
      return "重试运行";
    default:
      return statusLabel(event.action);
  }
}

function activityIcon(event: ActivityEvent): string {
  if (event.action === "issue.closure_needs_operator_review") return "!";
  if (event.action === "issue.review_closeout_missing") return "!";
  if (event.action === "issue.convergence_review_requested") return "!";
  if (event.action.includes("executed") || event.action.includes("heartbeat")) return "R";
  if (event.action.includes("status")) return "S";
  if (event.action.includes("review")) return "V";
  return event.actorType === "agent" ? "A" : "U";
}

function activityTone(event: ActivityEvent): string {
  if (event.action === "issue.closure_needs_operator_review") return "needs-attention";
  if (event.action === "issue.review_closeout_missing") return "needs-attention";
  if (event.action === "issue.convergence_review_requested") return "needs-review";
  if (event.action.includes("heartbeat") || event.action === "issue.executed") return "run";
  if (event.action.includes("review")) return "review";
  if (event.action.includes("status") || event.action === "issue.updated") return "status";
  if (event.action === "issue.created") return "created";
  return event.actorType === "agent" ? "agent" : "default";
}

function activityMeta(event: ActivityEvent): string {
  const parts = [formatIssueTime(event.createdAt)];
  if (event.runId) parts.push(`Run ${event.runId}`);
  const agentId = typeof event.details?.agentId === "string" ? event.details.agentId : event.agentId;
  if (agentId) parts.push(`Agent ${agentId}`);
  return parts.join(" · ");
}

function activityNumber(event: ActivityEvent, key: string): number | null {
  const value = event.details?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function issueCloseoutReviewSummary(event: ActivityEvent): string {
  const attempts = activityNumber(event, "attempts");
  const maxAttempts = activityNumber(event, "maxAttempts");
  const attemptText = attempts !== null && maxAttempts !== null ? ` ${attempts}/${maxAttempts} 次` : "";
  if (event.action === "issue.review_closeout_missing") {
    return `Reviewer 收口已尝试${attemptText}，但仍未提交结构化评审结论。`;
  }
  return `自动收口已尝试${attemptText}，智能体仍未明确完成、阻塞或提交评审。`;
}

function issueConvergenceReviewSummary(event: ActivityEvent): string {
  const attempts = activityNumber(event, "attempts");
  const maxAttempts = activityNumber(event, "maxAttempts");
  const attemptText = attempts !== null && maxAttempts !== null ? ` ${attempts}/${maxAttempts} 次` : "";
  return `自动收口已尝试${attemptText}，已转交 Reviewer 判断下一步。`;
}

function issueCloseoutReviewActivity(
  issue: IssueDetail,
  events: ActivityEvent[] | undefined,
  latestRun: HeartbeatRun | null,
): ActivityEvent | null {
  if (!Array.isArray(events) || !latestRun || !isTerminalRun(latestRun.status)) return null;
  const latestRunId = heartbeatRunId(latestRun);
  if (!latestRunId) return null;
  const matchesLatestRun = (event: ActivityEvent, action: string) =>
    event.action === action && event.entityType === "issue" && event.entityId === issue.id && event.runId === latestRunId;
  if (issue.status === "in_review") {
    return events.find((event) => matchesLatestRun(event, "issue.review_closeout_missing")) ?? null;
  }
  if (issue.status !== "in_progress") return null;
  return events.find((event) => matchesLatestRun(event, "issue.closure_needs_operator_review")) ?? null;
}

function runHasExplicitCloseoutSignal(run: HeartbeatRun | null, events: ActivityEvent[] | undefined, issueId: string): boolean {
  if (!run || !Array.isArray(events)) return false;
  const runId = heartbeatRunId(run);
  return events.some((event) => {
    if (event.entityType !== "issue" || event.entityId !== issueId || event.runId !== runId) return false;
    if (event.action === "issue.comment_added") return true;
    if (event.action !== "issue.updated") return false;
    const status = event.details?.status;
    return typeof status === "string" && ["done", "blocked", "in_review"].includes(status);
  });
}

type IssueTimelineItem =
  | { id: string; item: ActivityEvent; kind: "activity"; timestamp: string }
  | { id: string; item: IssueComment; kind: "comment"; timestamp: string };

function timelineTime(value: string): number {
  const time = Date.parse(value);
  return Number.isNaN(time) ? 0 : time;
}

function issueTimelineItems(
  events: ActivityEvent[] | undefined,
  comments: IssueComment[] | undefined,
): IssueTimelineItem[] {
  const items: IssueTimelineItem[] = [
    ...(Array.isArray(events)
      ? events.map((item) => ({
          id: `activity:${item.id}`,
          item,
          kind: "activity" as const,
          timestamp: item.createdAt,
        }))
      : []),
    ...(Array.isArray(comments)
      ? comments.map((item) => ({
          id: `comment:${item.id}`,
          item,
          kind: "comment" as const,
          timestamp: item.createdAt,
        }))
      : []),
  ];
  return items.sort((left, right) => timelineTime(left.timestamp) - timelineTime(right.timestamp));
}

function workProductSize(product: IssueWorkProduct): string {
  const metadataByteSize = product.metadata?.byteSize;
  const byteSize = typeof metadataByteSize === "number" ? metadataByteSize : product.byteSize;
  return byteSize !== undefined && byteSize !== null ? formatBytes(byteSize) : "-";
}

function workProductSummary(product: IssueWorkProduct): string {
  return product.summary ?? "server 已登记该产物。";
}

function mergeRunEvents(left: HeartbeatRunEvent[], right: HeartbeatRunEvent[]): HeartbeatRunEvent[] {
  const next = new Map<number, HeartbeatRunEvent>();
  for (const event of left) next.set(event.id, event);
  for (const event of right) next.set(event.id, event);
  return Array.from(next.values()).sort((leftEvent, rightEvent) => leftEvent.seq - rightEvent.seq);
}

function hasJsonObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function formattedJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function runSummary(run: HeartbeatRun | null): string {
  if (!run) return "暂无运行记录";
  const error = runErrorMessage(run.error);
  if (run.status === "cancelled" && error === "run cancelled") return isPassiveFollowupRun(run) ? "已停止" : "已取消";
  if (error) return error;
  if (run.summary?.trim()) return run.summary.trim();
  const result = hasJsonObject(run.resultJson) ? run.resultJson : null;
  for (const key of ["summary", "result", "message"]) {
    const value = result?.[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return statusLabel(run.status);
}

function latestRunBadgeLabel(run: HeartbeatRun | null | undefined): string {
  if (!run) return "";
  return isPassiveFollowupRun(run) ? "补充关闭信号运行" : "最新运行";
}

function latestRunStatusText(run: HeartbeatRun | null | undefined): string {
  if (!run) return "";
  if (run.status === "cancelled") return isPassiveFollowupRun(run) ? "已停止" : "已取消";
  return statusLabel(run.status);
}

function isUserCancelledRun(run: HeartbeatRun | null | undefined): boolean {
  return Boolean(run && run.status === "cancelled" && runErrorMessage(run.error) === "run cancelled");
}

function previewRunSummary(summary: string): string {
  if (summary.length <= RUN_SUMMARY_PREVIEW_CHARS) return summary;
  return `${summary.slice(0, RUN_SUMMARY_PREVIEW_CHARS).trimEnd()}...`;
}

function eventPayloadText(payload: Record<string, unknown> | null | undefined): string {
  if (!payload) return "";
  for (const key of ["text", "content", "message", "delta", "output"]) {
    const value = payload[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "";
}

function isLowValueRunEvent(event: HeartbeatRunEvent): boolean {
  const eventType = event.eventType.toLowerCase();
  return (
    eventType.includes("step_start") ||
    eventType.includes("step_finish") ||
    eventType.includes("step.start") ||
    eventType.includes("step.finish") ||
    eventType.includes("step.started") ||
    eventType.includes("step.finished")
  );
}

function isErrorRunEvent(event: HeartbeatRunEvent): boolean {
  const eventType = event.eventType.toLowerCase();
  return (
    event.level === "error" ||
    event.stream === "stderr" ||
    eventType.includes("stderr") ||
    eventType.includes("error") ||
    eventType.includes("failed")
  );
}

function isTextRunEvent(event: HeartbeatRunEvent): boolean {
  const eventType = event.eventType.toLowerCase();
  return (
    event.stream === "stdout" ||
    eventType.includes("text") ||
    eventType.includes("message") ||
    eventType.includes("output") ||
    Boolean(eventPayloadText(event.payload))
  );
}

function runEventLabel(event: HeartbeatRunEvent): string {
  const eventType = event.eventType.toLowerCase();
  if (eventType.includes("issue_review_requested")) return "请求评审";
  if (eventType.includes("issue_review_closeout_missing")) return "缺少评审结论";
  if (eventType.includes("issue_passive_followup")) return "补充关闭信号";
  if (eventType.includes("issue_execution_promoted")) return "延期任务已恢复执行";
  if (isErrorRunEvent(event)) return "错误";
  if (isTextRunEvent(event)) return "Agent 回复";
  if (eventType.includes("queued")) return "入队";
  if (eventType.includes("started") || eventType.includes("running")) return "开始";
  if (eventType.includes("progress")) return "运行进度";
  if (eventType.includes("adapter") || eventType.includes("runtime")) return "调用 adapter";
  if (eventType.includes("succeeded") || eventType.includes("completed")) return "成功";
  if (eventType.includes("cancel")) return "取消";
  return event.eventType;
}

function runEventBody(event: HeartbeatRunEvent): string {
  return eventPayloadText(event.payload) || event.message || "";
}

function shouldCollapseAgentReply(body: string): boolean {
  return body.length > AGENT_REPLY_COLLAPSE_CHARS || body.split(/\r?\n/).length > AGENT_REPLY_COLLAPSE_LINES;
}

function agentReplyPreview(body: string): string {
  const lines = body.split(/\r?\n/);
  const linePreview = lines.slice(0, AGENT_REPLY_COLLAPSE_LINES).join("\n");
  const preview = linePreview.length > AGENT_REPLY_COLLAPSE_CHARS
    ? `${linePreview.slice(0, AGENT_REPLY_COLLAPSE_CHARS).trimEnd()}...`
    : linePreview;
  return lines.length > AGENT_REPLY_COLLAPSE_LINES && !preview.endsWith("...") ? `${preview}\n...` : preview;
}

function parseJsonReply(body: string): unknown | null {
  const trimmed = body.trim();
  if (!trimmed || !["{", "["].includes(trimmed[0] ?? "")) return null;
  try {
    const parsed = JSON.parse(trimmed);
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}

function AgentReplyBody({ body }: { body: string }) {
  const json = parseJsonReply(body);
  const shouldCollapse = shouldCollapseAgentReply(body);
  const [expanded, setExpanded] = useState(!shouldCollapse);
  return (
    <div className="issue-run-agent-reply-block">
      <details className="issue-run-inline-details issue-run-agent-reply-details">
        <summary>回复详情</summary>
        {json !== null ? (
          <pre className="agent-run-json issue-run-agent-reply-json">{formattedJson(json)}</pre>
        ) : (
          <>
            <p className={`issue-run-agent-reply${shouldCollapse && !expanded ? " collapsed" : ""}`}>
              {expanded ? body : agentReplyPreview(body)}
            </p>
            {shouldCollapse && (
              <button
                className="secondary small-button issue-run-agent-reply-toggle"
                onClick={() => setExpanded((value) => !value)}
                type="button"
              >
                {expanded ? "收起回复" : "展开完整回复"}
              </button>
            )}
          </>
        )}
      </details>
    </div>
  );
}

function RunEventBody({ event }: { event: HeartbeatRunEvent }) {
  const body = runEventBody(event);
  if (!body) return null;
  if (isTextRunEvent(event) && !isErrorRunEvent(event)) return <AgentReplyBody body={body} />;
  return <pre className={`issue-run-event-log${isErrorRunEvent(event) ? " error" : ""}`}>{body}</pre>;
}

function formatIssueTime(value: string | null | undefined): string {
  return formatDateTime(value);
}

function numericUsageValue(run: HeartbeatRun, key: string): number {
  const value = run.usageJson?.[key];
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return 0;
}

function runHasReportedUsage(run: HeartbeatRun): boolean {
  const usage = run.usageJson;
  if (!usage || typeof usage !== "object") return false;
  if (["costCents", "costUsd", "inputTokens", "outputTokens", "cachedInputTokens", "totalTokens"].some((key) => numericUsageValue(run, key) > 0)) {
    return true;
  }
  const stdout = typeof run.resultJson?.stdout === "string" ? run.resultJson.stdout : "";
  return stdout.includes('"type":"step_finish"') || stdout.includes('"type":"turn.completed"');
}

function issueRunCostSummary(runs: HeartbeatRun[]): {
  cachedInputTokens: number;
  inputTokens: number;
  outputTokens: number;
  reportedRuns: number;
  totalCostCents: number;
  totalTokens: number;
  unreportedRuns: number;
} {
  return runs.reduce(
    (summary, run) => {
      if (runHasReportedUsage(run)) {
        summary.reportedRuns += 1;
      } else if (run.usageJson || ["succeeded", "failed", "cancelled", "timed_out"].includes(run.status)) {
        summary.unreportedRuns += 1;
      }
      const costCents = numericUsageValue(run, "costCents");
      const costUsd = numericUsageValue(run, "costUsd");
      const inputTokens = numericUsageValue(run, "inputTokens");
      const outputTokens = numericUsageValue(run, "outputTokens");
      const totalTokens = numericUsageValue(run, "totalTokens") || inputTokens + outputTokens;
      summary.totalCostCents += costCents || Math.round(costUsd * 100);
      summary.totalTokens += totalTokens;
      summary.inputTokens += inputTokens;
      summary.outputTokens += outputTokens;
      summary.cachedInputTokens += numericUsageValue(run, "cachedInputTokens");
      return summary;
    },
    { cachedInputTokens: 0, inputTokens: 0, outputTokens: 0, reportedRuns: 0, totalCostCents: 0, totalTokens: 0, unreportedRuns: 0 },
  );
}

function issueStatusOptionDisabledReason(issue: IssueDetail, status: IssueStatus): string {
  if (status === issue.status) return "";
  if (status === "in_review" && !issue.reviewerAgentId) return "请先设置 Reviewer。";
  if (["in_review", "blocked"].includes(issue.status) && ["done", "in_progress", "todo"].includes(status)) {
    return "请通过评审结论推进或退回任务。";
  }
  if (issue.status === "done") return "已完成任务请使用重新打开流程。";
  if (issue.status === "cancelled") return "已取消任务请使用重新打开流程。";
  return "";
}

function IssuePropertiesPanel({
  agents,
  goals,
  issue,
  isUpdating,
  latestRunStatus,
  onUpdate,
  projects,
}: {
  agents: Agent[];
  goals: Goal[];
  issue: IssueDetail;
  isUpdating: boolean;
  latestRunStatus?: HeartbeatRun["status"];
  onUpdate: (payload: UpdateIssuePayload) => void;
  projects: ProjectDetail[];
}) {
  const agentsById = new Map(agents.map((agent) => [agent.id, agent]));
  const statusSelectDisabledReason = isLiveRun(latestRunStatus) ? "当前任务已有运行在执行中，运行结束后再调整阶段。" : "";
  const statusSelectDisabled = isUpdating || Boolean(statusSelectDisabledReason);
  return (
    <section aria-label="任务属性" className="panel issue-properties-card">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Task Properties</p>
          <h2>属性</h2>
        </div>
      </div>
      <div className="issue-property-list">
        <label className="issue-property-row">
          <span>任务阶段</span>
          <select
            disabled={statusSelectDisabled}
            title={statusSelectDisabledReason || undefined}
            value={issue.status}
            onChange={(event) => onUpdate({ status: event.target.value as IssueStatus })}
          >
            {ISSUE_STATUSES.map((status) => {
              const disabledReason = issueStatusOptionDisabledReason(issue, status);
              return (
                <option disabled={Boolean(disabledReason)} key={status} title={disabledReason || undefined} value={status}>
                  {statusLabel(status)}
                </option>
              );
            })}
          </select>
        </label>
        <label className="issue-property-row">
          <span>优先级</span>
          <select disabled={isUpdating} value={issue.priority} onChange={(event) => onUpdate({ priority: event.target.value as IssuePriority })}>
            {ISSUE_PRIORITIES.map((priority) => <option key={priority} value={priority}>{priorityLabel(priority)}</option>)}
          </select>
        </label>
        <label className="issue-property-row">
          <span>负责人</span>
          <select
            disabled={isUpdating}
            value={nullableSelectValue(issue.assigneeAgentId)}
            onChange={(event) => {
              const nextAssigneeAgentId = event.target.value || null;
              onUpdate({
                assigneeAgentId: nextAssigneeAgentId,
                assigneeUserId: null,
                ...(nextAssigneeAgentId && nextAssigneeAgentId === issue.reviewerAgentId ? { reviewerAgentId: null, reviewerUserId: null } : {}),
              });
            }}
          >
            <option value="">未分配</option>
            {agents.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}
          </select>
        </label>
        {issue.assigneeAgentId && (
          <div className="issue-property-row issue-property-link-row">
            <span>负责人链接</span>
            <Link to={`/orgs/${issue.orgId}/agents/${issue.assigneeAgentId}`}>{agentName(issue.assigneeAgentId, agentsById)}</Link>
          </div>
        )}
        <label className="issue-property-row">
          <span>Reviewer</span>
          <select
            disabled={isUpdating}
            value={nullableSelectValue(issue.reviewerAgentId)}
            onChange={(event) => onUpdate({ reviewerAgentId: event.target.value || null, reviewerUserId: null })}
          >
            <option value="">不设置</option>
            {agents.map((agent) => (
              <option disabled={agent.id === issue.assigneeAgentId} key={agent.id} value={agent.id}>{agent.name}</option>
            ))}
          </select>
        </label>
        {issue.reviewerAgentId && (
          <div className="issue-property-row issue-property-link-row">
            <span>Reviewer 链接</span>
            <Link to={`/orgs/${issue.orgId}/agents/${issue.reviewerAgentId}`}>{agentName(issue.reviewerAgentId, agentsById)}</Link>
          </div>
        )}
        <label className="issue-property-row">
          <span>项目</span>
          <select
            disabled={isUpdating}
            value={nullableSelectValue(issue.projectId)}
            onChange={(event) => onUpdate({ projectId: event.target.value || null })}
          >
            <option value="">未关联</option>
            {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
          </select>
        </label>
        <label className="issue-property-row">
          <span>目标</span>
          <select
            disabled={isUpdating}
            value={nullableSelectValue(issue.goalId)}
            onChange={(event) => onUpdate({ goalId: event.target.value || null })}
          >
            <option value="">未关联</option>
            {goals.map((goal) => <option key={goal.id} value={goal.id}>{goal.title}</option>)}
          </select>
        </label>
        <label className="issue-property-row">
          <span>父任务</span>
          <input
            disabled={isUpdating}
            defaultValue={nullableSelectValue(issue.parentId)}
            key={issue.parentId ?? "empty-parent"}
            onBlur={(event) => {
              const nextParentId = event.target.value.trim() || null;
              if (nextParentId !== issue.parentId) onUpdate({ parentId: nextParentId });
            }}
            placeholder="父任务 ID"
          />
        </label>
        <div className="issue-property-row issue-property-disabled">
          <span>标签</span>
          <em>当前 server 未返回标签数据</em>
        </div>
        <hr className="issue-property-divider" />
        <div className="issue-property-row">
          <span>创建者</span>
          {issue.createdByAgentId ? (
            <Link to={`/orgs/${issue.orgId}/agents/${issue.createdByAgentId}`}>{agentName(issue.createdByAgentId, agentsById)}</Link>
          ) : (
            <strong>{issue.createdByUserId ?? "-"}</strong>
          )}
        </div>
        <div className="issue-property-row"><span>编号</span><strong>{issue.issueNumber ?? "-"}</strong></div>
        <div className="issue-property-row"><span>层级</span><strong>{issue.requestDepth}</strong></div>
        <div className="issue-property-row"><span>来源</span><strong>{issue.originKind}</strong></div>
        <div className="issue-property-row"><span>来源 ID</span><strong>{issue.originId ?? "-"}</strong></div>
        <div className="issue-property-row"><span>已启动</span><strong>{issue.startedAt ?? "-"}</strong></div>
        <div className="issue-property-row"><span>已完成</span><strong>{issue.completedAt ?? "-"}</strong></div>
        <div className="issue-property-row"><span>已创建</span><strong>{formatDateTime(issue.createdAt)}</strong></div>
        <div className="issue-property-row"><span>已更新</span><strong>{formatDateTime(issue.updatedAt)}</strong></div>
      </div>
    </section>
  );
}

function IssueCostPanel({ runs }: { runs: HeartbeatRun[] }) {
  const costSummary = issueRunCostSummary(runs);
  const hasReportedUsage = costSummary.reportedRuns > 0;
  const usageValue = (value: number) => hasReportedUsage ? value.toLocaleString() : "未上报";
  const costValue = hasReportedUsage ? formatMoneyCents(costSummary.totalCostCents) : "未上报";
  return (
    <section aria-label="任务成本" className="panel issue-cost-card">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Usage & Cost</p>
          <h2>成本</h2>
        </div>
      </div>
      <div className="issue-property-list">
        <div className="issue-property-row"><span>成本</span><strong>{costValue}</strong></div>
        <div className="issue-property-row"><span>Total tokens</span><strong>{usageValue(costSummary.totalTokens)}</strong></div>
        <div className="issue-property-row"><span>输入</span><strong>{usageValue(costSummary.inputTokens)}</strong></div>
        <div className="issue-property-row"><span>输出</span><strong>{usageValue(costSummary.outputTokens)}</strong></div>
        <div className="issue-property-row"><span>已缓存</span><strong>{usageValue(costSummary.cachedInputTokens)}</strong></div>
        {!hasReportedUsage && costSummary.unreportedRuns > 0 && (
          <p className="muted">当前运行未上报 token/cost 事件。</p>
        )}
      </div>
    </section>
  );
}

function IssueQueueStatusPanel({
  activeRuns,
  agentsById,
  currentRun,
  issue,
  orgId,
}: {
  activeRuns: HeartbeatRun[];
  agentsById: Map<string, Agent>;
  currentRun: HeartbeatRun | null;
  issue: IssueDetail;
  orgId: string;
}) {
  if (!currentRun || !isLiveRun(currentRun.status) || activeRuns.length === 0 || !issue.assigneeAgentId) return null;
  const aheadCount = queueRunsAhead(activeRuns, currentRun);
  const assigneeName = agentName(issue.assigneeAgentId, agentsById);
  const counts = queueSourceCounts(activeRuns);
  const previewRuns = activeRuns.slice(0, 4);
  function queueRunIssueLabel(run: HeartbeatRun): string {
    if (run.issueId === issue.id) return issue.identifier ?? issue.title ?? issue.id;
    return runIssueLabel(run) ?? "";
  }
  return (
    <section aria-label="运行队列状态" className="issue-queue-status">
      <div className="issue-queue-status-heading">
        <div>
          <p className="eyebrow">QUEUE</p>
          <h2>运行队列</h2>
        </div>
        <StatusPill status={currentRun.status}>{statusLabel(currentRun.status)}</StatusPill>
      </div>
      <p>
        {assigneeName} 正在处理 {activeRuns.length} 个活跃运行；当前任务前面还有 {aheadCount} 个运行。
      </p>
      <div className="issue-queue-source-list" aria-label="队列来源">
        {counts.map((item) => (
          <span key={item.source}>
            {sourceLabel(item.source)}
            <strong>{item.count}</strong>
          </span>
        ))}
      </div>
      <div className="issue-queue-run-list">
        {previewRuns.map((run) => (
          <article className={heartbeatRunId(run) === heartbeatRunId(currentRun) ? "current" : ""} key={heartbeatRunId(run)}>
            <span>{run.id.slice(0, 8)}</span>
            <Badge>{run.invocationSource}</Badge>
            <small title={runDescriptor(run)}>{runDescriptor(run)}</small>
            {queueRunIssueLabel(run) && <small>{queueRunIssueLabel(run)}</small>}
            <StatusPill status={run.status}>{statusLabel(run.status)}</StatusPill>
          </article>
        ))}
      </div>
      <Link className="button secondary small-button" to={`/orgs/${orgId}/agents/${issue.assigneeAgentId}/runs`}>打开负责人运行页</Link>
    </section>
  );
}

function IssueWorkProductsPanel({ embedded = false, issue, latestRunStatus }: { embedded?: boolean; issue: IssueDetail; latestRunStatus?: HeartbeatRun["status"] }) {
  const queryClient = useQueryClient();
  const [workProductsExpanded, setWorkProductsExpanded] = useState(!embedded);
  const workProductsQuery = useQuery({
    queryKey: ["issue-work-products", issue.id],
    queryFn: () => issuesApi.listWorkProducts(issue.id),
    initialData: issue.workProducts ?? [],
  });
  const workProducts = workProductsQuery.data ?? [];
  const deleteWorkProduct = useMutation({
    mutationFn: (workProductId: string) => issuesApi.deleteWorkProduct(workProductId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["issue-work-products", issue.id] });
      void queryClient.invalidateQueries({ queryKey: ["issue", issue.id] });
    },
  });
  return (
    <section aria-label="运行产物" className={embedded ? "issue-run-output-block" : "issue-section-card"}>
      <div className={embedded ? "issue-run-output-heading" : "issue-section-heading"}>
        <div>
          {embedded ? (
            <h3>任务产物</h3>
          ) : (
            <>
              <p className="eyebrow">ARTIFACTS</p>
              <h2>运行产物</h2>
            </>
          )}
        </div>
        <div className={embedded ? "issue-run-operation-actions" : "issue-section-heading-actions"}>
          {embedded && (
            <button aria-label={workProductsExpanded ? "折叠任务产物" : `展开任务产物 ${workProducts.length}`} className="secondary small-button" type="button" onClick={() => setWorkProductsExpanded((value) => !value)}>
              {workProductsExpanded ? "折叠" : `展开 ${workProducts.length}`}
            </button>
          )}
        </div>
      </div>
      {!workProductsExpanded ? (
        <p className="muted">任务产物已折叠。</p>
      ) : (
        <>
      {workProductsQuery.error && <ErrorNotice error={workProductsQuery.error} />}
      {workProductsQuery.isLoading && <p className="muted">加载工作产物中...</p>}
      {!workProductsQuery.isLoading && workProducts.length === 0 && (
        <p className="muted">
          {latestRunStatus === "succeeded"
            ? "最新运行已成功，但 server 没有登记受管产物。可能没有生成文件，或文件写到了工作区 / artifacts 之外的路径。"
            : "暂无运行产物。任务执行成功后，server 会把受管工作区或 artifacts 中的产物登记到这里。"}
        </p>
      )}
      {workProducts.length > 0 && (
        <div className="issue-work-product-list">
          {workProducts.map((product) => {
            const workspaceBrowserPath = metadataString(product.metadata, "workspaceBrowserPath");
            const displayName = workProductDisplayName(product);
            return (
            <article className="issue-work-product-card" key={product.id}>
              <div className="issue-work-product-title-row">
                <div>
                  <strong>{displayName}</strong>
                  <p>{workProductSummary(product)}</p>
                </div>
                <Badge>{workProductSourceLabel(product)}</Badge>
              </div>
              <div className="issue-work-product-meta">
                <Badge>{product.type}</Badge>
                <StatusPill status={product.status}>{statusLabel(product.status)}</StatusPill>
                <StatusPill status={product.reviewState}>{statusLabel(product.reviewState)}</StatusPill>
                {product.isPrimary && <Badge>primary</Badge>}
              </div>
              <dl className="issue-work-product-details">
                <div><dt>大小</dt><dd>{workProductSize(product)}</dd></div>
                <div><dt>运行</dt><dd>{product.createdByRunId ? product.createdByRunId.slice(0, 8) : "-"}</dd></div>
                <div><dt>健康</dt><dd>{statusLabel(product.healthStatus)}</dd></div>
              </dl>
              <details className="storage-object-details">
                <summary>技术详情</summary>
                <dl className="issue-work-product-details">
                  {product.title !== displayName && <div><dt>原始标题</dt><dd>{product.title}</dd></div>}
                  <div><dt>工作区</dt><dd>{product.executionWorkspaceId ?? "-"}</dd></div>
                  <div><dt>工作区路径</dt><dd>{metadataText(product.metadata, "workspacePath")}</dd></div>
                  <div><dt>浏览路径</dt><dd>{metadataText(product.metadata, "workspaceBrowserPath")}</dd></div>
                  <div><dt>来源</dt><dd>{metadataText(product.metadata, "source")}</dd></div>
                  <div><dt>运行</dt><dd>{product.createdByRunId ?? "-"}</dd></div>
                  {product.assetId && <div><dt>资产</dt><dd>{product.assetId}</dd></div>}
                  <div><dt>provider</dt><dd>{product.provider}</dd></div>
                  <div><dt>大小</dt><dd>{workProductSize(product)}</dd></div>
                  <div><dt>contentType</dt><dd>{product.contentType ?? "-"}</dd></div>
                  <div><dt>sha256</dt><dd>{product.sha256 ?? "-"}</dd></div>
                </dl>
              </details>
              <div className="issue-work-product-actions">
                {product.contentPath ? (
                  <>
                    <a className="button secondary small-button" href={product.contentPath}>下载运行产物</a>
                    <a className="button secondary small-button" href={product.contentPath} target="_blank" rel="noreferrer">预览内容</a>
                  </>
                ) : (
                  <span className="download-unavailable">不可下载</span>
                )}
                {workspaceBrowserPath && (
                  <Link
                    className="button secondary small-button"
                    to={`/orgs/${issue.orgId}/workspaces?path=${encodeURIComponent(workspaceBrowserPath)}`}
                  >
                    在工作区打开
                  </Link>
                )}
                {product.url && <a className="button secondary small-button" href={product.url}>打开运行产物</a>}
                <button
                  className="danger small-button"
                  disabled={deleteWorkProduct.isPending}
                  onClick={() => deleteWorkProduct.mutate(product.id)}
                  type="button"
                >
                  删除产物
                </button>
              </div>
            </article>
          );
          })}
        </div>
      )}
      {deleteWorkProduct.error && <ErrorNotice error={deleteWorkProduct.error} />}
        </>
      )}
    </section>
  );
}

function IssueDocumentsPanel({ embedded = false, issueId }: { embedded?: boolean; issueId: string }) {
  const queryClient = useQueryClient();
  const [documentsHidden, setDocumentsHidden] = useState(true);
  const [selectedKey, setSelectedKey] = useState<string>("");
  const [draftKey, setDraftKey] = useState("");
  const [draftTitle, setDraftTitle] = useState("");
  const [draftBody, setDraftBody] = useState("");
  const [changeSummary, setChangeSummary] = useState("");
  const documents = useQuery({
    queryKey: ["issue-documents", issueId],
    queryFn: () => issuesApi.listDocuments(issueId),
  });
  useEffect(() => {
    if (selectedKey || !documents.data?.[0]) return;
    setSelectedKey(documents.data[0].key);
  }, [documents.data, selectedKey]);
  const document = useQuery({
    queryKey: ["issue-document", issueId, selectedKey],
    queryFn: () => issuesApi.getDocument(issueId, selectedKey),
    enabled: Boolean(selectedKey),
  });
  const revisions = useQuery({
    queryKey: ["issue-document-revisions", issueId, selectedKey],
    queryFn: () => issuesApi.listDocumentRevisions(issueId, selectedKey),
    enabled: Boolean(selectedKey),
  });
  useEffect(() => {
    if (!document.data) return;
    setDraftKey(document.data.key);
    setDraftTitle(document.data.title ?? "");
    setDraftBody(document.data.body);
    setChangeSummary("");
  }, [document.data]);
  const saveDocument = useMutation({
    mutationFn: () => issuesApi.upsertDocument(issueId, draftKey.trim(), {
      title: draftTitle.trim() || null,
      format: "markdown",
      body: draftBody,
      changeSummary: changeSummary.trim() || null,
      baseRevisionId: document.data?.latestRevisionId ?? null,
    }),
    onSuccess: (saved) => {
      setSelectedKey(saved.key);
      void queryClient.invalidateQueries({ queryKey: ["issue", issueId] });
      void queryClient.invalidateQueries({ queryKey: ["issue-documents", issueId] });
      void queryClient.invalidateQueries({ queryKey: ["issue-document", issueId, saved.key] });
      void queryClient.invalidateQueries({ queryKey: ["issue-document-revisions", issueId, saved.key] });
    },
  });
  const deleteDocument = useMutation({
    mutationFn: () => issuesApi.deleteDocument(issueId, selectedKey),
    onSuccess: () => {
      setSelectedKey("");
      setDraftKey("");
      setDraftTitle("");
      setDraftBody("");
      setChangeSummary("");
      void queryClient.invalidateQueries({ queryKey: ["issue", issueId] });
      void queryClient.invalidateQueries({ queryKey: ["issue-documents", issueId] });
    },
  });
  function startNewDocument() {
    setSelectedKey("");
    setDraftKey("");
    setDraftTitle("");
    setDraftBody("");
    setChangeSummary("");
  }
  const canSave = Boolean(draftKey.trim() && draftBody.trim());
  return (
    <section aria-label="任务文档" className={embedded ? "issue-run-output-block" : "issue-section-card"}>
      <div className="issue-section-heading">
        <div>
          <p className="eyebrow">DOCUMENTS</p>
          <h2>任务文档</h2>
        </div>
        <div className="issue-section-heading-actions">
          <button
            aria-label={documentsHidden ? "展开任务文档" : "折叠任务文档"}
            className="secondary small-button"
            onClick={() => setDocumentsHidden((value) => !value)}
            type="button"
          >
            {documentsHidden ? "展开" : "折叠"}
          </button>
        </div>
      </div>
      {!documentsHidden && (
        <>
          <p className="muted issue-work-product-hint">
            文档由 server 按任务保存，支持查看正文、编辑保存、查看历史版本和删除。
          </p>
          {documents.error && <ErrorNotice error={documents.error} />}
          <div className="issue-documents-layout">
            <aside className="issue-document-list" aria-label="文档列表">
              <button className="secondary small-button" onClick={startNewDocument} type="button">新建文档</button>
              {documents.isLoading && <p className="muted">加载文档中...</p>}
              {documents.isSuccess && documents.data.length === 0 && <p className="muted">暂无文档。</p>}
              {documents.data?.map((item) => (
                <button
                  className={selectedKey === item.key ? "active" : ""}
                  key={item.id}
                  onClick={() => setSelectedKey(item.key)}
                  type="button"
                >
                  <strong>{item.title || item.key}</strong>
                  <span>{item.key} · v{item.latestRevisionNumber}</span>
                </button>
              ))}
            </aside>
            <div className="issue-document-editor">
              {document.error && <ErrorNotice error={document.error} />}
              <div className="issue-document-fields">
                <label>
                  文档 key
                  <input
                    disabled={Boolean(document.data)}
                    placeholder="plan"
                    value={draftKey}
                    onChange={(event) => setDraftKey(event.target.value)}
                  />
                </label>
                <label>
                  标题
                  <input value={draftTitle} onChange={(event) => setDraftTitle(event.target.value)} />
                </label>
              </div>
              <label>
                正文
                <textarea
                  className="issue-document-body"
                  placeholder="输入 Markdown 文档内容"
                  value={draftBody}
                  onChange={(event) => setDraftBody(event.target.value)}
                />
              </label>
              <label>
                变更说明
                <input value={changeSummary} onChange={(event) => setChangeSummary(event.target.value)} />
              </label>
              <div className="issue-work-product-actions">
                <button disabled={!canSave || saveDocument.isPending} onClick={() => saveDocument.mutate()} type="button">
                  保存文档
                </button>
                <button
                  className="danger small-button"
                  disabled={!selectedKey || deleteDocument.isPending}
                  onClick={() => deleteDocument.mutate()}
                  type="button"
                >
                  删除文档
                </button>
              </div>
              {saveDocument.error && <ErrorNotice error={saveDocument.error} />}
              {deleteDocument.error && <ErrorNotice error={deleteDocument.error} />}
              <details className="storage-object-details">
                <summary>历史版本</summary>
                {revisions.error && <ErrorNotice error={revisions.error} />}
                {revisions.isLoading && selectedKey && <p className="muted">加载历史版本中...</p>}
                {revisions.data?.map((revision) => (
                  <article className="issue-document-revision" key={revision.id}>
                    <strong>v{revision.revisionNumber}</strong>
                    <span>{revision.changeSummary || "无变更说明"} · {formatDateTime(revision.createdAt)}</span>
                  </article>
                ))}
                {revisions.isSuccess && revisions.data.length === 0 && <p className="muted">暂无历史版本。</p>}
              </details>
            </div>
          </div>
        </>
      )}
    </section>
  );
}

function IssueRunsPanel({
  agentsById,
  currentRunId,
  embedded = false,
  expandedRunIds,
  onSelect,
  onToggle,
  renderRunDetails,
  runs,
}: {
  agentsById: Map<string, Agent>;
  currentRunId: string;
  embedded?: boolean;
  expandedRunIds: Set<string>;
  onSelect: (runId: string) => void;
  onToggle: (runId: string) => void;
  renderRunDetails?: (runId: string) => ReactNode;
  runs: HeartbeatRun[];
}) {
  const displayRuns = [...runs].sort((left, right) => runSortTime(left) - runSortTime(right));
  const [expandedSummaryRunIds, setExpandedSummaryRunIds] = useState<Set<string>>(() => new Set());
  const content = runs.length === 0 ? (
    <p className="muted">暂无运行记录。</p>
  ) : (
    <div className="issue-run-record-list">
      {displayRuns.map((run, index) => {
        const runId = heartbeatRunId(run);
        const displayRun = run;
        const source = displayRun.invocationSource?.trim();
        const wakeReason = runWakeReason(displayRun);
        const summary = runSummary(displayRun);
        const summaryExpanded = expandedSummaryRunIds.has(runId);
        const summaryExpandable = summary.length > RUN_SUMMARY_PREVIEW_CHARS;
        const visibleSummary = summaryExpanded || !summaryExpandable ? summary : previewRunSummary(summary);
        const isSelected = runId === currentRunId;
        const isExpanded = expandedRunIds.has(runId);
        const isReviewRun = displayRun.invocationSource === "review";
        const isPassiveFollowupRun =
          displayRun.invocationSource === "automation" &&
          wakeReason === "issue_passive_followup";
        const runTypeClass = isReviewRun
          ? "review"
          : isPassiveFollowupRun
            ? "followup"
            : "task";
        const runTypeLabel = isReviewRun
          ? "Reviewer 评审"
          : isPassiveFollowupRun
            ? "收尾跟进"
            : runPurposeLabel(displayRun);
        return (
          <article className={`issue-run-record-group ${runTypeClass}${isSelected ? " active" : ""}${isExpanded ? " expanded" : ""}`} key={runId}>
            <div className={`issue-run-record-main-row${isSelected ? " active" : ""}`}>
              <button
                className={`issue-run-record${isSelected ? " active" : ""}`}
                onClick={() => onSelect(runId)}
                type="button"
              >
                <span className="issue-run-record-index">第 {index + 1} 次</span>
                <div className="issue-run-record-header">
                  <div className="issue-run-record-title">
                    <strong>{runId}</strong>
                    <span className="issue-run-record-badges">
                      <span className={`badge issue-run-type-badge ${runTypeClass}`}>{runTypeLabel}</span>
                      {source && <Badge>来源 {source}</Badge>}
                      {wakeReason && <Badge>触发原因 {wakeReason}</Badge>}
                      <StatusPill status={displayRun.status}>{statusLabel(displayRun.status)}</StatusPill>
                    </span>
                  </div>
                </div>
                <dl className="issue-run-record-meta">
                  <div><dt>执行智能体</dt><dd>{agentName(displayRun.agentId, agentsById)}</dd></div>
                  <div><dt>创建时间</dt><dd>{formatIssueTime(displayRun.createdAt)}</dd></div>
                  <div><dt>开始时间</dt><dd>{formatIssueTime(displayRun.startedAt)}</dd></div>
                </dl>
              </button>
              {summary && (
                <div className={`issue-run-record-summary${summaryExpanded ? " expanded" : ""}`}>
                  <span>输出摘要</span>
                  <p>
                    {summaryExpandable && !summaryExpanded ? (
                      visibleSummary.slice(0, -3)
                    ) : summaryExpandable && summaryExpanded ? (
                      visibleSummary
                    ) : (
                      visibleSummary
                    )}
                  </p>
                  {summaryExpandable && (
                    <button
                      aria-label={summaryExpanded ? `收起运行摘要 ${runId}` : `展开运行摘要 ${runId}`}
                      className="issue-run-summary-more"
                      title={summaryExpanded ? "收起摘要" : "展开摘要"}
                      onClick={() => {
                        setExpandedSummaryRunIds((current) => {
                          const next = new Set(current);
                          if (summaryExpanded) {
                            next.delete(runId);
                          } else {
                            next.add(runId);
                          }
                          return next;
                        });
                      }}
                      type="button"
                    >
                      {summaryExpanded ? "收起" : "展开"}
                    </button>
                  )}
                </div>
              )}
              <button
                aria-label={isExpanded ? `折叠运行 ${runId}` : `展开运行 ${runId}`}
                className="secondary small-button issue-run-record-toggle"
                onClick={() => onToggle(runId)}
                type="button"
              >
                {isExpanded ? "折叠" : "展开"}
              </button>
            </div>
            {isExpanded && renderRunDetails && (
              <div className="issue-run-record-details">
                {renderRunDetails(runId)}
              </div>
            )}
          </article>
        );
      })}
    </div>
  );
  if (embedded) return content;
  return (
    <section aria-label="运行记录" className="issue-section-card">
      <div className="issue-section-heading">
        <div>
          <p className="eyebrow">RUNS</p>
          <h2>运行记录</h2>
        </div>
        <span className="muted">{runs.length} 次运行</span>
      </div>
      {content}
    </section>
  );
}

interface IssueRunPanelData {
  events: UseQueryResult<HeartbeatRunEvent[], Error>;
  operations: UseQueryResult<WorkspaceOperation[], Error>;
  run: UseQueryResult<HeartbeatRun, Error>;
}

function PaginatedLogView({
  emptyText,
  loadMore,
  loadingText,
  log,
  preClassName,
}: {
  emptyText: string;
  loadMore: (offset: number) => Promise<LogReadResult>;
  loadingText: string;
  log: UseQueryResult<LogReadResult, Error>;
  preClassName: string;
}) {
  const [content, setContent] = useState("");
  const [cursor, setCursor] = useState<number | null>(null);
  const [eof, setEof] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadMoreError, setLoadMoreError] = useState<Error | null>(null);

  useEffect(() => {
    const data = log.data;
    if (!data) {
      setContent("");
      setCursor(null);
      setEof(true);
      setLoadMoreError(null);
      return;
    }
    setContent(data.content ?? "");
    setCursor(data.eof === false ? nextLogOffset(data) : null);
    setEof(data.eof !== false);
    setLoadMoreError(null);
  }, [log.data?.content, log.data?.endOffset, log.data?.eof, log.data?.nextOffset]);

  async function handleLoadMore() {
    if (cursor === null || loadingMore) return;
    setLoadingMore(true);
    setLoadMoreError(null);
    try {
      const next = await loadMore(cursor);
      setContent((current) => `${current}${next.content ?? ""}`);
      setCursor(next.eof === false ? nextLogOffset(next) : null);
      setEof(next.eof !== false);
    } catch (error) {
      setLoadMoreError(error instanceof Error ? error : new Error("日志读取失败"));
    } finally {
      setLoadingMore(false);
    }
  }

  return (
    <>
      {log.isLoading && <p className="muted">{loadingText}</p>}
      {!log.isLoading && !content && <p className="muted">{emptyText}</p>}
      {content && <AutoScrollPre className={preClassName} content={content} />}
      {!eof && cursor !== null && (
        <div className="issue-run-operation-actions">
          <button
            className="secondary small-button"
            disabled={loadingMore}
            onClick={handleLoadMore}
            type="button"
          >
            {loadingMore ? "读取中..." : "加载更多日志"}
          </button>
          <span className="muted">已读取到 {formatBytes(cursor)}</span>
        </div>
      )}
      {loadMoreError && <ErrorNotice error={loadMoreError} />}
    </>
  );
}

function WorkspaceOperationLogPanel({ operation }: { operation: WorkspaceOperation }) {
  const operationLog = useQuery({
    queryKey: ["workspace-operation-log", operation.id],
    queryFn: () => heartbeatApi.getWorkspaceOperationLog(operation.id),
    refetchInterval: () => operation.status === "running" ? LIVE_RUN_REFETCH_MS : false,
  });
  return (
    <div className="issue-run-operation-log">
      {operationLog.error && <ErrorNotice error={operationLog.error} />}
      <PaginatedLogView
        emptyText="暂无操作日志。"
        loadMore={(offset) => heartbeatApi.getWorkspaceOperationLog(operation.id, { offset })}
        loadingText="加载操作日志中..."
        log={operationLog}
        preClassName="issue-run-event-log"
      />
    </div>
  );
}

function IssueRunOutputPanel({
  cancelling,
  data,
  embedded = false,
  onCancel,
  onRetry,
  retrying,
  runId,
  streamActive,
  streamError,
  streamLog,
}: {
  cancelling: boolean;
  data: IssueRunPanelData;
  embedded?: boolean;
  onCancel: () => void;
  onRetry: (run: HeartbeatRun) => void;
  retrying: boolean;
  runId: string;
  streamActive: boolean;
  streamError: string | null;
  streamLog: string;
}) {
  const [showEvents, setShowEvents] = useState(false);
  const [showOperations, setShowOperations] = useState(true);
  const [showRawOutput, setShowRawOutput] = useState(true);
  const [showLiveLogDelta, setShowLiveLogDelta] = useState(true);
  const [showRunLog, setShowRunLog] = useState(true);
  const [showLowValueEvents, setShowLowValueEvents] = useState(false);
  const [viewMode, setViewMode] = useState<"nice" | "raw">("nice");
  const run = data.run.data ?? null;
  const suppressUserCancelError = isUserCancelledRun(run);
  const events = data.events.data ?? [];
  const operations = data.operations.data ?? [];
  const visibleEvents = events.filter((event) => !isLowValueRunEvent(event));
  const lowValueEvents = events.filter(isLowValueRunEvent);
  const hasRawOutput = Boolean(run?.stdoutExcerpt || run?.stderrExcerpt || operations.some((operation) => operation.command || operation.stdoutExcerpt || operation.stderrExcerpt));
  const runLog = useQuery({
    queryKey: ["heartbeat-run-log", runId],
    queryFn: () => heartbeatApi.getLog(runId),
    enabled: Boolean(runId),
    refetchInterval: () => isLiveRun(run?.status) ? LIVE_RUN_REFETCH_MS : false,
  });
  const liveRun = isLiveRun(run?.status);
  const wakeReason = runWakeReason(run);
  const isReviewRun = run?.invocationSource === "review";
  const isPassiveFollowupRun =
    run?.invocationSource === "automation" &&
    wakeReason === "issue_passive_followup";
  const canRetryRun =
    Boolean(run) &&
    (isReviewRun || isPassiveFollowupRun) &&
    ["failed", "timed_out", "cancelled"].includes(run.status);
  const retryRunLabel = isReviewRun ? "Reviewer 评审" : "收尾跟进";
  const liveLogDelta = streamLogDelta(streamLog, runLog.data?.content);
  const lastEvent = events.at(-1) ?? null;
  const hasVisibleRuntimeOutput = Boolean(
    liveLogDelta ||
    runLog.data?.content ||
    run?.stdoutExcerpt ||
    run?.stderrExcerpt ||
    visibleEvents.some((event) => isTextRunEvent(event) && runEventBody(event))
  );
  const processPid = typeof run?.processPid === "number" ? run.processPid : null;
  const silentRuntimeText = liveRun && !hasVisibleRuntimeOutput
    ? `${processPid ? `进程 ${processPid} 已启动` : "运行已启动"}，等待 runtime 输出。`
    : "";
  useEffect(() => {
    setViewMode("nice");
    setShowLiveLogDelta(true);
  }, [runId]);
  return (
    <>
      <section aria-label="执行输出" className={embedded ? "issue-run-output-block issue-run-output" : "issue-section-card issue-run-output"}>
      <div className="issue-run-output-heading">
        <div>
          <h3>执行输出</h3>
        </div>
        <div className="issue-run-actions">
          {liveRun && runElapsedText(run) && <Badge>已运行 {runElapsedText(run)}</Badge>}
          {processPid && <Badge>PID {processPid}</Badge>}
          {streamActive && <Badge>stream 连接中</Badge>}
          {liveRun && !streamActive && <Badge>动态刷新中</Badge>}
          {liveRun && (
            <button
              aria-label={`取消运行 ${runId}`}
              className="secondary small-button"
              disabled={cancelling}
              onClick={onCancel}
              type="button"
            >
              {cancelling ? "取消中" : "取消运行"}
            </button>
          )}
          <div className="agent-run-view-toggle" aria-label="任务执行视图">
            <button className={viewMode === "nice" ? "active" : ""} onClick={() => setViewMode("nice")} type="button">Nice</button>
            <button className={viewMode === "raw" ? "active" : ""} onClick={() => setViewMode("raw")} type="button">Raw</button>
          </div>
          {run && <Link className="button secondary small-button" to={`/orgs/${run.orgId}/agents/${run.agentId}/runs`}>打开运行页</Link>}
          {run && canRetryRun && (
            <button
              aria-label={`重新执行 ${retryRunLabel} ${runId}`}
              className="secondary small-button"
              disabled={retrying}
              onClick={() => onRetry(run)}
              type="button"
            >
              {retrying ? "提交中" : "重新执行"}
            </button>
          )}
        </div>
      </div>
      <>
          {run?.error && !suppressUserCancelError && <ErrorNotice error={run.error} />}
          {data.events.error && <ErrorNotice error={data.events.error} />}
          {data.operations.error && <ErrorNotice error={data.operations.error} />}
          {runLog.error && <ErrorNotice error={runLog.error} />}
          {streamError && <p className="error-notice">{streamError}</p>}
      {viewMode === "raw" && liveLogDelta && (
        <section className="issue-run-output-block">
          <div className="issue-run-output-heading">
            <div>
              <h3
                aria-expanded={showLiveLogDelta}
                className="issue-run-heading-toggle"
                onClick={() => setShowLiveLogDelta((value) => !value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    setShowLiveLogDelta((value) => !value);
                  }
                }}
                tabIndex={0}
              >
                实时日志增量
              </h3>
            </div>
            <Badge>stream</Badge>
          </div>
          {showLiveLogDelta ? (
            <AutoScrollPre className="run-excerpt inline" content={liveLogDelta} />
          ) : (
            <p className="muted">实时日志增量已折叠。</p>
          )}
        </section>
      )}
      {viewMode === "nice" && silentRuntimeText && (
        <section className="issue-run-progress-note" aria-label="运行进度提示">
          <strong>{silentRuntimeText}</strong>
          {lastEvent && (
            <span>
              最近进度：{runEventBody(lastEvent) || lastEvent.message || runEventLabel(lastEvent)}
              <small>{formatDateTime(lastEvent.createdAt)}</small>
            </span>
          )}
        </section>
      )}
      <section className="issue-run-output-block">
        <div className="issue-run-output-heading">
          <div>
            <h3>运行日志</h3>
            {liveRun && <p className="muted">运行中会通过 stream 动态刷新事件和输出。</p>}
          </div>
          <div className="issue-run-operation-actions">
            {showRunLog && runLog.data?.eof === false && <Badge>可继续读取</Badge>}
            <button aria-label={showRunLog ? "折叠运行日志" : "展开运行日志"} className="secondary small-button" type="button" onClick={() => setShowRunLog((value) => !value)}>
              {showRunLog ? "折叠" : "展开"}
            </button>
          </div>
        </div>
        {!showRunLog ? (
          <p className="muted">运行日志已折叠。</p>
        ) : (
          <PaginatedLogView
            emptyText="暂无运行日志。"
            loadMore={(offset) => heartbeatApi.getLog(runId, { offset })}
            loadingText="加载运行日志中..."
            log={runLog}
            preClassName="run-excerpt inline"
          />
        )}
      </section>
      {viewMode === "raw" && run && (
        <section className="issue-run-output-block">
          <h3>Raw 数据</h3>
          <div className="issue-run-raw-stack">
            {hasJsonObject(run.resultJson) && (
              <details className="issue-run-inline-details">
                <summary>resultJson</summary>
                <pre className="agent-run-json">{formattedJson(run.resultJson)}</pre>
              </details>
            )}
            {hasJsonObject(run.contextSnapshot) && (
              <details className="issue-run-inline-details">
                <summary>contextSnapshot</summary>
                <pre className="agent-run-json">{formattedJson(run.contextSnapshot)}</pre>
              </details>
            )}
            {hasJsonObject(run.usageJson) && (
              <details className="issue-run-inline-details">
                <summary>usageJson</summary>
                <pre className="agent-run-json">{formattedJson(run.usageJson)}</pre>
              </details>
            )}
          </div>
        </section>
      )}
      </>
      </section>
      <section className="issue-run-output-block issue-run-events-flat">
        <div className="issue-run-output-heading">
          <h3>关键事件</h3>
          <div className="issue-run-operation-actions">
            <button aria-label={showEvents ? "折叠关键事件" : `展开关键事件 ${events.length}`} className="secondary small-button" type="button" onClick={() => setShowEvents((value) => !value)}>
              {showEvents ? "折叠" : `展开 ${events.length}`}
            </button>
            {viewMode === "raw" && showEvents && lowValueEvents.length > 0 && (
              <button aria-label={showLowValueEvents ? "折叠低价值事件" : `展开低价值事件 ${lowValueEvents.length}`} className="secondary small-button" type="button" onClick={() => setShowLowValueEvents((value) => !value)}>
                {showLowValueEvents ? "折叠低价值事件" : `展开低价值事件 ${lowValueEvents.length}`}
              </button>
            )}
          </div>
        </div>
        {!showEvents ? (
          <p className="muted">关键事件已折叠。</p>
        ) : (
          <>
            {data.events.isLoading && <p className="muted">加载事件中...</p>}
            {!data.events.isLoading && events.length === 0 && <p className="muted">暂无事件。</p>}
            {!data.events.isLoading && events.length > 0 && visibleEvents.length === 0 && (
              <p className="muted">{viewMode === "nice" ? "暂无关键事件。切换 Raw 可查看低价值事件。" : "暂无可展示事件。"}</p>
            )}
            {visibleEvents.length > 0 && (
              <div className={viewMode === "nice" ? "agent-run-events compact" : "agent-run-events"}>
                {visibleEvents.map((event) => (
                  <article className={`agent-run-event${viewMode === "nice" ? " compact" : ""} issue-run-timeline-event${isErrorRunEvent(event) ? " error" : ""}${isTextRunEvent(event) ? " agent-reply" : ""}`} key={event.id}>
                    <div className="agent-run-event-header">
                      <span>#{event.seq}</span>
                      <strong>{runEventLabel(event)}</strong>
                      <Badge>{event.eventType}</Badge>
                      {event.level && <StatusPill status={event.level}>{statusLabel(event.level)}</StatusPill>}
                      {event.stream && <Badge>{event.stream}</Badge>}
                    </div>
                    <RunEventBody event={event} />
                    {viewMode === "raw" && hasJsonObject(event.payload) && (
                      <details className="issue-run-inline-details">
                        <summary>事件详情</summary>
                        <pre className="agent-run-json issue-run-event-payload">{formattedJson(event.payload)}</pre>
                      </details>
                    )}
                    <small className="muted">{formatDateTime(event.createdAt)}</small>
                  </article>
                ))}
              </div>
            )}
            {viewMode === "raw" && showLowValueEvents && lowValueEvents.length > 0 && (
              <div className="issue-run-low-value-events">
                {lowValueEvents.map((event) => (
                  <article className="agent-run-event compact" key={event.id}>
                    <div className="agent-run-event-header">
                      <span>#{event.seq}</span>
                      <strong>{event.eventType}</strong>
                    </div>
                    {event.message && <p className="muted">{event.message}</p>}
                  </article>
                ))}
              </div>
            )}
          </>
        )}
      </section>
      <section className="issue-run-output-block">
        <div className="issue-run-output-heading">
          <h3>工作区操作</h3>
          <div className="issue-run-operation-actions">
            <button aria-label={showOperations ? "折叠工作区操作" : `展开工作区操作 ${operations.length}`} className="secondary small-button" type="button" onClick={() => setShowOperations((value) => !value)}>
              {showOperations ? "折叠" : `展开 ${operations.length}`}
            </button>
          </div>
        </div>
        {!showOperations ? (
          <p className="muted">工作区操作已折叠。</p>
        ) : (
          <>
        {data.operations.isLoading && <p className="muted">加载工作区操作中...</p>}
        {!data.operations.isLoading && operations.length === 0 && <p className="muted">暂无工作区操作。</p>}
        {operations.length > 0 && (
          <div className={viewMode === "nice" ? "agent-run-events compact" : "agent-run-events"}>
            {operations.map((operation) => (
              <article className={`agent-run-event${viewMode === "nice" ? " compact" : ""}`} key={operation.id}>
                <div className="agent-run-event-header">
                  <strong>{operation.phase}</strong>
                  <StatusPill status={operation.status}>{statusLabel(operation.status)}</StatusPill>
                  {operation.exitCode !== undefined && operation.exitCode !== null && <Badge>Exit {operation.exitCode}</Badge>}
                </div>
                {operation.command && <p className="muted">{operation.command}</p>}
                {viewMode === "raw" && operation.stderrExcerpt && <pre className="run-excerpt error inline">{operation.stderrExcerpt}</pre>}
                <small className="muted">{operation.cwd ?? operation.id}</small>
                {viewMode === "raw" && operation.logBytes !== undefined && operation.logBytes !== null && (
                  <span className="muted">{formatBytes(operation.logBytes)}</span>
                )}
                {viewMode === "raw" && <WorkspaceOperationLogPanel operation={operation} />}
              </article>
            ))}
          </div>
        )}
          </>
        )}
      </section>
      {viewMode === "raw" && <section className="issue-run-output-block issue-run-debug-output">
        <div className="issue-run-output-heading">
          <h3>原始输出</h3>
          <div className="issue-run-operation-actions">
            <button aria-label={showRawOutput ? "折叠原始输出" : "展开原始输出"} className="secondary small-button" type="button" onClick={() => setShowRawOutput((value) => !value)}>
              {showRawOutput ? "折叠" : "展开"}
            </button>
          </div>
        </div>
        {!showRawOutput ? (
          <p className="muted">原始输出已折叠。</p>
        ) : !hasRawOutput ? (
          <p className="muted">暂无原始输出。</p>
        ) : (
          <div className="issue-run-stream-list">
            {run?.stdoutExcerpt && (
              <article className="agent-run-event">
                <div className="agent-run-event-header">
                  <strong>stdout</strong>
                  <Badge>原始输出</Badge>
                </div>
                <pre className="run-excerpt inline">{run.stdoutExcerpt}</pre>
              </article>
            )}
            {run?.stderrExcerpt && (
              <article className="agent-run-event error">
                <div className="agent-run-event-header">
                  <strong>stderr</strong>
                  <Badge>错误</Badge>
                </div>
                <pre className="run-excerpt error inline">{run.stderrExcerpt}</pre>
              </article>
            )}
            {operations.map((operation) => (
              <article className="agent-run-event" key={operation.id}>
                <div className="agent-run-event-header">
                  <strong>{operation.phase}</strong>
                  <StatusPill status={operation.status}>{statusLabel(operation.status)}</StatusPill>
                </div>
                {operation.command && <pre className="issue-run-event-log">{operation.command}</pre>}
                {operation.stderrExcerpt && <pre className="run-excerpt error inline">{operation.stderrExcerpt}</pre>}
                {operation.stdoutExcerpt && <pre className="run-excerpt inline">{operation.stdoutExcerpt}</pre>}
              </article>
            ))}
          </div>
        )}
      </section>}
    </>
  );
}

function IssueRunDetailsPanel({
  issue,
  issueId,
  latestRunStatus,
  onCancelRun,
  onRetryRun,
  orgId,
  cancellingRunId,
  retryingRunId,
  runId,
}: {
  issue: IssueDetail;
  issueId: string;
  latestRunStatus?: HeartbeatRun["status"];
  onCancelRun: (run: HeartbeatRun) => void;
  onRetryRun: (run: HeartbeatRun) => void;
  orgId: string;
  cancellingRunId?: string;
  retryingRunId?: string;
  runId: string;
}) {
  const queryClient = useQueryClient();
  const streamCursorRef = useRef<RunStreamCursor>({ lastSeq: 0, nextOffset: 0 });
  const [heartbeatContextExpanded, setHeartbeatContextExpanded] = useState(true);
  const [streamActive, setStreamActive] = useState(false);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [streamLog, setStreamLog] = useState("");
  const runDetail = useQuery({
    queryKey: ["heartbeat-run", runId],
    queryFn: () => heartbeatApi.get(runId),
    enabled: Boolean(runId),
    refetchInterval: (query) => isLiveRun(query.state.data?.status) ? LIVE_RUN_REFETCH_MS : false,
  });
  const runEvents = useQuery({
    queryKey: ["heartbeat-run-events", runId],
    queryFn: async () => {
      const fetched = await heartbeatApi.listEvents(runId);
      const cached = queryClient.getQueryData<HeartbeatRunEvent[]>(["heartbeat-run-events", runId]) ?? [];
      return mergeRunEvents(cached, fetched);
    },
    enabled: Boolean(runId),
    refetchInterval: () => isLiveRun(runDetail.data?.status) ? LIVE_RUN_REFETCH_MS : false,
  });
  const runWorkspaceOperations = useQuery({
    queryKey: ["heartbeat-run-workspace-operations", runId],
    queryFn: () => heartbeatApi.listWorkspaceOperations(runId),
    enabled: Boolean(runId),
    refetchInterval: () => isLiveRun(runDetail.data?.status) ? LIVE_RUN_REFETCH_MS : false,
  });
  const heartbeatContext = useQuery({
    queryKey: ["issue-heartbeat-context", issueId],
    queryFn: () => issuesApi.heartbeatContext(issueId),
    enabled: Boolean(issueId),
  });
  useEffect(() => {
    if (!runId || !isLiveRun(runDetail.data?.status)) return;
    const cursor = streamCursorRef.current;
    const controller = new AbortController();
    setStreamActive(true);
    setStreamError(null);
    void heartbeatApi.streamRun(runId, {
      afterSeq: cursor.lastSeq,
      offset: cursor.nextOffset,
      pollMs: LIVE_RUN_REFETCH_MS,
      signal: controller.signal,
      onRun: (run) => {
        queryClient.setQueryData<HeartbeatRun>(["heartbeat-run", runId], (current) => ({
          ...current,
          ...run,
        }));
      },
      onEvent: (event) => {
        cursor.lastSeq = Math.max(cursor.lastSeq, event.seq);
        queryClient.setQueryData<HeartbeatRunEvent[]>(["heartbeat-run-events", runId], (current = []) => mergeRunEvents(current, [event]));
      },
      onLog: (payload) => {
        if (typeof payload.nextOffset === "number") cursor.nextOffset = payload.nextOffset;
        if (payload.content) setStreamLog((current) => `${current}${payload.content}`);
      },
      onFinal: (run) => {
        queryClient.setQueryData<HeartbeatRun>(["heartbeat-run", runId], (current) => ({
          ...current,
          ...run,
        }));
        setStreamActive(false);
        void queryClient.invalidateQueries({ queryKey: ["issue", issueId] });
        void queryClient.invalidateQueries({ queryKey: ["issues", orgId] });
        void queryClient.invalidateQueries({ queryKey: ["issue-heartbeat-runs", issueId] });
        void queryClient.invalidateQueries({ queryKey: ["heartbeat-runs", orgId] });
        void queryClient.invalidateQueries({ queryKey: ["issue-documents", issueId] });
        void queryClient.invalidateQueries({ queryKey: ["issue-work-products", issueId] });
      },
      onError: (error) => {
        setStreamError(error);
        setStreamActive(false);
      },
    }).catch((error: unknown) => {
      if (controller.signal.aborted) return;
      setStreamError(error instanceof Error ? error.message : "Run stream failed");
      void queryClient.invalidateQueries({ queryKey: ["heartbeat-run", runId] });
      void queryClient.invalidateQueries({ queryKey: ["issue-heartbeat-runs", issueId] });
    }).finally(() => {
      if (!controller.signal.aborted) setStreamActive(false);
    });
    return () => {
      controller.abort();
      setStreamActive(false);
    };
  }, [issueId, orgId, queryClient, runDetail.data?.status, runId]);

  return (
    <>
      <IssueRunOutputPanel
        cancelling={cancellingRunId === runId}
        data={{
          events: runEvents,
          operations: runWorkspaceOperations,
          run: runDetail,
        }}
        embedded
        onCancel={() => {
          if (runDetail.data) onCancelRun(runDetail.data);
        }}
        onRetry={onRetryRun}
        retrying={retryingRunId === runId}
        runId={runId}
        streamActive={streamActive}
        streamError={streamError}
        streamLog={streamLog}
      />

      <section aria-label="心跳上下文" className="issue-run-output-block">
        <div className="issue-run-output-heading">
          <div>
            <h3>心跳上下文</h3>
          </div>
          <div className="issue-run-operation-actions">
            <button aria-label={heartbeatContextExpanded ? "折叠心跳上下文" : "展开心跳上下文"} className="secondary small-button" type="button" onClick={() => setHeartbeatContextExpanded((value) => !value)}>
              {heartbeatContextExpanded ? "折叠" : "展开"}
            </button>
          </div>
        </div>
        {!heartbeatContextExpanded ? (
          <p className="muted">心跳上下文已折叠。</p>
        ) : (
          <>
        {heartbeatContext.isLoading && <p className="muted">加载上下文中...</p>}
        {heartbeatContext.error && <ErrorNotice error={heartbeatContext.error} />}
        {heartbeatContext.data && (
          <details className="issue-run-inline-details">
            <summary>心跳上下文详情</summary>
            <pre className="agent-run-json">{formattedJson(heartbeatContext.data)}</pre>
          </details>
        )}
          </>
        )}
      </section>

      <IssueWorkProductsPanel embedded issue={issue} latestRunStatus={latestRunStatus} />
    </>
  );
}

export function IssuePage() {
  const { orgId = "", issueId = "" } = useParams();
  const [comment, setComment] = useState("");
  const [mentionQuery, setMentionQuery] = useState<{ start: number; query: string } | null>(null);
  const [attachmentFile, setAttachmentFile] = useState<File | null>(null);
  const [attachmentUploadNotice, setAttachmentUploadNotice] = useState("");
  const [attachmentMenuOpen, setAttachmentMenuOpen] = useState(false);
  const [executeNotice, setExecuteNotice] = useState("");
  const [subIssueTitle, setSubIssueTitle] = useState("");
  const [reviewNotice, setReviewNotice] = useState("");
  const [currentRunId, setCurrentRunId] = useState(() => {
    if (!orgId || !issueId) return "";
    return localStorage.getItem(issueRunStorageKey(orgId, issueId)) ?? "";
  });
  const [expandedRunIds, setExpandedRunIds] = useState<Set<string>>(() => new Set());
  const commentTextareaRef = useRef<HTMLTextAreaElement | null>(null);
  const autoExpandedLiveRunRef = useRef("");
  const refreshedTerminalRunRef = useRef("");
  const queryClient = useQueryClient();
  const agents = useQuery({ queryKey: ["agents", orgId], queryFn: () => agentsApi.list(orgId) });
  const goals = useQuery({ queryKey: ["goals", orgId], queryFn: () => goalsApi.list(orgId) });
  const issue = useQuery({ queryKey: ["issue", issueId], queryFn: () => issuesApi.get(issueId) });
  const projects = useQuery({ queryKey: ["projects", orgId], queryFn: () => projectsApi.list(orgId) });
  const comments = useQuery({
    queryKey: ["comments", issueId],
    queryFn: () => issuesApi.listComments(issueId),
  });
  const issueActivity = useQuery({
    queryKey: ["issue-activity", issueId],
    queryFn: () => activityApi.listIssue(issueId),
    enabled: Boolean(issueId),
  });
  const attachments = useQuery({
    queryKey: ["issue-attachments", issueId],
    queryFn: () => issuesApi.listAttachments(issueId),
  });
  const issueRuns = useQuery({
    queryKey: ["issue-heartbeat-runs", issueId],
    queryFn: () => issuesApi.listRuns(issueId),
    enabled: Boolean(issueId),
    refetchInterval: (query) => query.state.data?.some((run) => isLiveRun(run.status)) ? LIVE_RUN_REFETCH_MS : false,
  });
  const orgHeartbeatRuns = useQuery({
    queryKey: ["heartbeat-runs", orgId],
    queryFn: () => heartbeatApi.list(orgId),
    enabled: Boolean(orgId && issue.data?.assigneeAgentId),
    refetchInterval: (query) => query.state.data?.some((run) => isLiveRun(run.status)) ? LIVE_RUN_REFETCH_MS : false,
  });
  const subIssues = useQuery({
    queryKey: ["issues", orgId, "children", issueId],
    queryFn: () => issuesApi.list(orgId, { parentId: issueId }),
    enabled: Boolean(orgId && issueId),
    refetchInterval: (query) => {
      const children = Array.isArray(query.state.data) ? query.state.data : [];
      return issueRuns.data?.some((run) => isLiveRun(run.status)) || children.some((child) => isOpenIssueStatus(child.status))
        ? LIVE_RUN_REFETCH_MS
        : false;
    },
  });
  useEffect(() => {
    if (!orgId || !issueId) return;
    const storedRunId = localStorage.getItem(issueRunStorageKey(orgId, issueId)) ?? "";
    setCurrentRunId(storedRunId);
    setExpandedRunIds(new Set());
    autoExpandedLiveRunRef.current = "";
  }, [orgId, issueId]);
  useEffect(() => {
    if (currentRunId || !issueRuns.data?.length || !orgId || !issueId) return;
    const latestRun = latestIssueRun(issueRuns.data, null, issueId) ?? issueRuns.data[0];
    const latestRunId = heartbeatRunId(latestRun);
    if (!latestRunId) return;
    localStorage.setItem(issueRunStorageKey(orgId, issueId), latestRunId);
    setCurrentRunId(latestRunId);
  }, [currentRunId, issueRuns.data, issueId, orgId]);
  useEffect(() => {
    if (!orgId || !issueId || !issueRuns.data?.length) return;
    const latestRun = latestIssueRun(issueRuns.data, null, issueId);
    const latestRunId = heartbeatRunId(latestRun);
    if (!latestRunId || latestRun?.status !== "running") return;
    if (autoExpandedLiveRunRef.current === latestRunId) return;
    autoExpandedLiveRunRef.current = latestRunId;
    localStorage.setItem(issueRunStorageKey(orgId, issueId), latestRunId);
    setCurrentRunId(latestRunId);
    setExpandedRunIds((current) => {
      if (current.has(latestRunId)) return current;
      const next = new Set(current);
      next.add(latestRunId);
      return next;
    });
  }, [issueId, issueRuns.data, orgId]);
  useEffect(() => {
    if (!reviewNotice) return;
    const timer = window.setTimeout(() => setReviewNotice(""), 3000);
    return () => window.clearTimeout(timer);
  }, [reviewNotice]);
  useEffect(() => {
    if (!executeNotice) return;
    const timer = window.setTimeout(() => setExecuteNotice(""), 3000);
    return () => window.clearTimeout(timer);
  }, [executeNotice]);
  useEffect(() => {
    setReviewNotice("");
  }, [issue.data?.reviewerAgentId, issue.data?.status]);
  const addComment = useMutation({
    mutationFn: () => issuesApi.addComment(issueId, { body: comment.trim() }),
    onSuccess: () => {
      setComment("");
      setMentionQuery(null);
      void queryClient.invalidateQueries({ queryKey: ["comments", issueId] });
    },
  });
  const updateIssue = useMutation({
    mutationFn: (payload: UpdateIssuePayload) => issuesApi.update(issueId, payload),
    onSuccess: (updated) => {
      queryClient.setQueryData(["issue", issueId], updated);
      void queryClient.invalidateQueries({ queryKey: ["issues", orgId] });
    },
  });
  const createSubIssue = useMutation({
    mutationFn: () => {
      if (!issue.data) throw new Error("任务未加载");
      const reviewerAgentId =
        issue.data.reviewerAgentId && issue.data.reviewerAgentId !== issue.data.assigneeAgentId
          ? issue.data.reviewerAgentId
          : undefined;
      return issuesApi.create(orgId, {
        title: subIssueTitle.trim(),
        parentId: issue.data.id,
        projectId: issue.data.projectId,
        goalId: issue.data.goalId,
        assigneeAgentId: issue.data.assigneeAgentId,
        ...(reviewerAgentId ? { reviewerAgentId } : {}),
        priority: issue.data.priority,
        status: "todo",
      });
    },
    onSuccess: (created) => {
      setSubIssueTitle("");
      queryClient.setQueryData<IssueListItem[]>(["issues", orgId, "children", issueId], (current = []) => [
        ...current.filter((item) => item.id !== created.id),
        created,
      ]);
      void queryClient.invalidateQueries({ queryKey: ["issues", orgId, "children", issueId] });
      void queryClient.invalidateQueries({ queryKey: ["issues", orgId] });
    },
  });
  const executeIssue = useMutation({
    mutationFn: async () => {
      if (!issue.data?.assigneeAgentId) throw new Error("请先分配负责人");
      if (["done", "cancelled"].includes(issue.data.status)) throw new Error("请先重新打开任务，再启动执行");
      if (issue.data.status !== "in_progress") {
        await issuesApi.update(issue.data.id, { status: "in_progress" });
      }
      return issuesApi.execute(issue.data.id);
    },
    onSuccess: async (run) => {
      const runId = heartbeatRunId(run);
      if (runId) {
        setExecuteNotice(isLiveRun(run.status) ? `已连接到运行 ${runId}` : `已创建运行 ${runId}`);
        localStorage.setItem(issueRunStorageKey(orgId, issueId), runId);
        setCurrentRunId(runId);
        setExpandedRunIds(new Set());
        queryClient.setQueryData<HeartbeatRun>(["heartbeat-run", runId], (current) => ({
          ...current,
          ...run,
        }));
        queryClient.setQueryData<HeartbeatRun[]>(["issue-heartbeat-runs", issueId], (current = []) => [
          run,
          ...current.filter((item) => heartbeatRunId(item) !== runId),
        ]);
      } else {
        setExecuteNotice("执行请求已提交，暂未返回新的运行记录，正在刷新任务运行。");
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["issue", issueId] }),
        queryClient.invalidateQueries({ queryKey: ["issue-activity", issueId] }),
        queryClient.invalidateQueries({ queryKey: ["issues", orgId] }),
        queryClient.invalidateQueries({ queryKey: ["heartbeat-runs", orgId] }),
        queryClient.invalidateQueries({ queryKey: ["heartbeat-run", currentRunId] }),
        queryClient.invalidateQueries({ queryKey: ["heartbeat-run-events", currentRunId] }),
      ]);
    },
  });
  const passiveFollowup = useMutation({
    mutationFn: async () => {
      if (!issue.data) throw new Error("任务未加载");
      return issuesApi.passiveFollowup(issue.data.id);
    },
    onSuccess: async (run) => {
      const runId = heartbeatRunId(run);
      if (runId) {
        setExecuteNotice(`已创建收尾跟进 ${runId}`);
        localStorage.setItem(issueRunStorageKey(orgId, issueId), runId);
        setCurrentRunId(runId);
        queryClient.setQueryData<HeartbeatRun>(["heartbeat-run", runId], (current) => ({
          ...current,
          ...run,
        }));
        queryClient.setQueryData<HeartbeatRun[]>(["issue-heartbeat-runs", issueId], (current = []) => [
          run,
          ...current.filter((item) => heartbeatRunId(item) !== runId),
        ]);
      } else {
        setExecuteNotice("已提交收尾跟进，正在刷新任务运行。");
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["issue-heartbeat-runs", issueId] }),
        queryClient.invalidateQueries({ queryKey: ["issue-activity", issueId] }),
        queryClient.invalidateQueries({ queryKey: ["heartbeat-runs", orgId] }),
        queryClient.invalidateQueries({ queryKey: ["issue", issueId] }),
      ]);
    },
  });
  const retryRun = useMutation({
    mutationFn: (run: HeartbeatRun) => heartbeatApi.retry(heartbeatRunId(run)),
    onSuccess: (run) => {
      const retriedRunId = heartbeatRunId(run);
      if (retriedRunId) {
        localStorage.setItem(issueRunStorageKey(orgId, issueId), retriedRunId);
        setCurrentRunId(retriedRunId);
        setExpandedRunIds((current) => new Set(current).add(retriedRunId));
        queryClient.setQueryData<HeartbeatRun[]>(["issue-heartbeat-runs", issueId], (current = []) => [
          run,
          ...current.filter((item) => heartbeatRunId(item) !== retriedRunId),
        ]);
      }
      void queryClient.invalidateQueries({ queryKey: ["issue-heartbeat-runs", issueId] });
      void queryClient.invalidateQueries({ queryKey: ["heartbeat-runs", orgId] });
    },
  });
  const cancelIssueRun = useMutation({
    mutationFn: (run: HeartbeatRun) => heartbeatApi.cancel(heartbeatRunId(run)),
    onSuccess: (run) => {
      const cancelledRunId = heartbeatRunId(run);
      queryClient.setQueryData(["heartbeat-run", cancelledRunId], run);
      queryClient.setQueryData<HeartbeatRun[]>(["issue-heartbeat-runs", issueId], (current = []) =>
        current.map((item) => heartbeatRunId(item) === cancelledRunId ? run : item),
      );
      queryClient.setQueryData<HeartbeatRun[]>(["heartbeat-runs", orgId], (current = []) =>
        current.map((item) => heartbeatRunId(item) === cancelledRunId ? run : item),
      );
      void queryClient.invalidateQueries({ queryKey: ["issue-heartbeat-runs", issueId] });
      void queryClient.invalidateQueries({ queryKey: ["heartbeat-runs", orgId] });
      void queryClient.invalidateQueries({ queryKey: ["issue", issueId] });
      void queryClient.invalidateQueries({ queryKey: ["issues", orgId] });
    },
  });
  const checkoutIssue = useMutation({
    mutationFn: () => {
      if (!issue.data?.assigneeAgentId) throw new Error("请先分配负责人");
      return issuesApi.checkout(issue.data.id, {
        agentId: issue.data.assigneeAgentId,
        expectedStatuses: [issue.data.status],
      });
    },
    onSuccess: (updated) => {
      queryClient.setQueryData(["issue", issueId], updated);
      void queryClient.invalidateQueries({ queryKey: ["issues", orgId] });
    },
  });
  useEffect(() => {
    const latestRun = latestTerminalRunForIssue(issueRuns.data ?? [], issueId);
    const latestRunId = heartbeatRunId(latestRun);
    if (!latestRunId) return;
    const refreshKey = `${latestRunId}:${latestRun?.status}`;
    if (refreshedTerminalRunRef.current === refreshKey) return;
    refreshedTerminalRunRef.current = refreshKey;
    void queryClient.invalidateQueries({ queryKey: ["issue", issueId] });
    void queryClient.invalidateQueries({ queryKey: ["issues", orgId] });
    void queryClient.invalidateQueries({ queryKey: ["issue-activity", issueId] });
    void queryClient.invalidateQueries({ queryKey: ["issue-documents", issueId] });
    void queryClient.invalidateQueries({ queryKey: ["issue-work-products", issueId] });
  }, [issueId, issueRuns.data, orgId, queryClient]);
  const review = useMutation({
    mutationFn: (decision: IssueReviewDecision) => issuesApi.review(issueId, { decision }),
    onSuccess: () => {
      setReviewNotice("");
      void queryClient.invalidateQueries({ queryKey: ["issue", issueId] });
    },
  });
  const uploadAttachment = useMutation({
    mutationFn: (file?: File) => {
      const selectedFile = file ?? attachmentFile;
      if (!selectedFile) throw new Error("请选择附件文件");
      return issuesApi.uploadAttachment(orgId, issueId, {
        file: selectedFile,
        usage: "attachment",
      });
    },
    onSuccess: (_, file) => {
      setAttachmentUploadNotice(`已上传 ${file?.name ?? attachmentFile?.name ?? "附件"}`);
      setAttachmentFile(null);
      setAttachmentMenuOpen(false);
      void queryClient.invalidateQueries({ queryKey: ["issue-attachments", issueId] });
    },
    onMutate: () => {
      setAttachmentUploadNotice("");
    },
  });
  const deleteAttachment = useMutation({
    mutationFn: (attachmentId: string) => issuesApi.deleteAttachment(attachmentId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["issue-attachments", issueId] }),
  });
  useEffect(() => {
    if (!issue.data) return;
    writeRecentIssue(orgId, {
      id: issue.data.id,
      title: issue.data.title,
      identifier: issue.data.identifier,
      status: issue.data.status,
    });
  }, [issue.data, orgId]);
  function submitComment(event: FormEvent) {
    event.preventDefault();
    if (comment.trim()) addComment.mutate();
  }
  function submitCommentFromKeyboard(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    if (comment.trim() && !addComment.isPending) addComment.mutate();
  }
  function updateCommentMention(value: string, cursor: number | null | undefined) {
    const position = typeof cursor === "number" ? cursor : value.length;
    setMentionQuery(mentionQueryAtCursor(value, position));
  }
  function changeComment(value: string, cursor: number | null | undefined) {
    setComment(value);
    updateCommentMention(value, cursor);
  }
  function insertMention(agent: Agent) {
    if (!mentionQuery) return;
    const textarea = commentTextareaRef.current;
    const cursor = textarea?.selectionStart ?? comment.length;
    const token = agentMentionToken(agent);
    const nextComment = `${comment.slice(0, mentionQuery.start)}@${token} ${comment.slice(cursor)}`;
    const nextCursor = mentionQuery.start + token.length + 2;
    setComment(nextComment);
    setMentionQuery(null);
    window.setTimeout(() => {
      textarea?.focus();
      textarea?.setSelectionRange(nextCursor, nextCursor);
    }, 0);
  }
  const timelineItems = issueTimelineItems(issueActivity.data, comments.data);
  function selectAttachment(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    setAttachmentFile(file);
    setAttachmentUploadNotice("");
    if (file) uploadAttachment.mutate(file);
    event.target.value = "";
  }
  function submitSubIssue(event: FormEvent) {
    event.preventDefault();
    if (subIssueTitle.trim()) createSubIssue.mutate();
  }
  function submitReviewDecision(decision: IssueReviewDecision) {
    if (!issue.data) return;
    const blockReason = reviewDecisionBlockReason(issue.data);
    if (blockReason) {
      setReviewNotice(blockReason);
      return;
    }
    setReviewNotice("");
    review.mutate(decision);
  }
  function markIssueInReview() {
    if (!issue.data) return;
    const blockReason = markReviewBlockReason(issue.data);
    if (blockReason) {
      setReviewNotice(blockReason);
      return;
    }
    setReviewNotice("");
    updateIssue.mutate({ status: "in_review" });
  }
  function executeCurrentIssue() {
    const latestRun = latestIssueRun(issueRuns.data ?? [], null, issueId);
    if (uploadAttachment.isPending) {
      setExecuteNotice("附件上传中，上传完成后再启动执行。");
      return;
    }
    if (isLiveRun(latestRun?.status)) {
      setExecuteNotice("当前任务已有运行在执行中，请等待结束后再重新执行。");
      return;
    }
    if (!issue.data?.assigneeAgentId) {
      setExecuteNotice("请先分配负责人，再启动执行。");
      return;
    }
    if (["done", "cancelled"].includes(issue.data.status)) {
      setExecuteNotice("请先重新打开任务，再启动执行。");
      return;
    }
    setExecuteNotice(isRerunnableRun(latestRun?.status) ? "正在提交重新执行请求..." : "正在提交执行请求...");
    executeIssue.mutate();
  }
  if (issue.error) return <ErrorNotice error={issue.error} />;
  const agentList = Array.isArray(agents.data) ? agents.data : [];
  const agentsById = new Map(agentList.map((agent) => [agent.id, agent]));
  const mentionCandidates = mentionQuery
    ? agentList
        .filter((agent) => {
          const query = mentionQuery.query;
          if (!query) return true;
          return [agent.name, agent.urlKey, agent.id].some((value) => typeof value === "string" && value.toLowerCase().includes(query));
        })
        .slice(0, 8)
    : [];
  const goalList = Array.isArray(goals.data) ? goals.data : [];
  const projectList = Array.isArray(projects.data) ? projects.data : [];
  const subIssueList = Array.isArray(subIssues.data) ? subIssues.data : [];
  const latestRun = latestIssueRun(issueRuns.data ?? [], null, issueId);
  const latestRunError = runErrorMessage(latestRun?.error);
  const latestRunErrorNotice =
    latestRun && isUserCancelledRun(latestRun)
      ? null
      : latestRunError;
  const activeAssigneeRuns = activeQueueRunsForAgent(orgHeartbeatRuns.data ?? [], issue.data?.assigneeAgentId);
  const cancellingRunId =
    cancelIssueRun.isPending && cancelIssueRun.variables
      ? heartbeatRunId(cancelIssueRun.variables)
      : undefined;
  const latestRunIsLive = isLiveRun(latestRun?.status);
  const latestRunCanReexecute = isRerunnableRun(latestRun?.status);
  const latestRunSucceeded = latestRun?.status === "succeeded";
  const latestAnyRun = latestAnyRunForIssue(issueRuns.data ?? [], issueId);
  const latestCloseoutRun = latestTerminalRunForIssue(issueRuns.data ?? [], issueId);
  const closeoutReviewActivity =
    issue.data && !isLiveRun(latestAnyRun?.status)
      ? issueCloseoutReviewActivity(issue.data, issueActivity.data, latestCloseoutRun)
      : null;
  const latestRunHasCloseoutSignal = issue.data && latestRun ? runHasExplicitCloseoutSignal(latestRun, issueActivity.data, issue.data.id) : false;
  const needsCloseoutPrompt = issue.data
    ? latestRunSucceeded &&
      ["todo", "in_progress"].includes(issue.data.status) &&
      !closeoutReviewActivity &&
      !latestRunHasCloseoutSignal
    : false;
  const hideLatestRunError =
    executeIssue.isPending ||
    executeNotice.startsWith("正在提交") ||
    executeNotice.startsWith("执行请求已提交") ||
    executeNotice.startsWith("已连接到运行") ||
    executeNotice.startsWith("已创建运行");
  const executeButtonLabel = executeIssue.isPending
    ? "提交中"
    : latestRunCanReexecute
      ? "重新执行"
      : latestRunSucceeded
        ? "再次执行"
        : "启动执行";
  const executeBlockReason = uploadAttachment.isPending
    ? "附件上传中，上传完成后再启动执行"
    : latestRunIsLive
      ? "当前任务已有运行在执行中，请等待结束后再重新执行"
      : issue.data && ["done", "cancelled"].includes(issue.data.status)
        ? "请先重新打开任务，再启动执行"
        : issue.data?.assigneeAgentId
          ? ""
          : "请先分配负责人";
  return (
    <IssuesWorkspace contentClassName="org-content-full" orgId={orgId}>
      {agents.error && <ErrorNotice error={agents.error} />}
      {goals.error && <ErrorNotice error={goals.error} />}
      {projects.error && <ErrorNotice error={projects.error} />}
      {orgHeartbeatRuns.error && <ErrorNotice error={orgHeartbeatRuns.error} />}
      {issue.data && (
        <div className="issue-detail-layout">
          <header className="issue-detail-top">
            <nav aria-label="任务导航" className="issue-breadcrumb">
              <Link to={`/orgs/${orgId}/issues`}>任务</Link>
              <span>/</span>
              <span>{issueDisplayId(issue.data)}</span>
            </nav>

            <div className="issue-detail-title-block">
              <div className="issue-detail-kicker">
                <Badge>{issueDisplayId(issue.data)}</Badge>
                <Badge>任务状态：{statusLabel(issue.data.status)}</Badge>
                <Badge>{priorityLabel(issue.data.priority)}</Badge>
                {latestRun && (
                  <StatusPill status={latestRun.status}>
                    {latestRunBadgeLabel(latestRun)}：{latestRunStatusText(latestRun)}
                  </StatusPill>
                )}
              </div>
              <div className="issue-title-row">
                <h1>{issue.data.title}</h1>
                <div className="issue-header-actions">
                  <button
                    aria-disabled={executeBlockReason ? "true" : undefined}
                    className={executeBlockReason ? "is-disabled" : undefined}
                    disabled={executeIssue.isPending}
                    title={executeBlockReason || (latestRunCanReexecute ? "重新交给负责人启动一次运行" : "交给负责人启动一次运行")}
                    type="button"
                    onClick={executeCurrentIssue}
                  >
                    {executeButtonLabel}
                  </button>
                  <button
                    className="secondary small-button"
                    disabled={checkoutIssue.isPending || !issue.data.assigneeAgentId}
                    title={issue.data.assigneeAgentId ? "由当前负责人签出任务" : "请先分配负责人"}
                    type="button"
                    onClick={() => checkoutIssue.mutate()}
                  >
                    签出任务
                  </button>
                  <button className="secondary small-button" type="button" onClick={() => navigator.clipboard?.writeText(issueDisplayId(issue.data))}>
                    复制 ID
                  </button>
                  <Link className="button secondary small-button" to={`/orgs/${orgId}/chats`}>聊天</Link>
                </div>
              </div>
            </div>
            {executeIssue.error && <ErrorNotice error={executeIssue.error} />}
            {checkoutIssue.error && <ErrorNotice error={checkoutIssue.error} />}
            {executeNotice && <p className="issue-action-notice" role="status">{executeNotice}</p>}
            {latestRun && isRerunnableRun(latestRun.status) && latestRunErrorNotice && !hideLatestRunError && (
              <p className="error-notice" role="status">
                {latestRunBadgeLabel(latestRun)}：{latestRunStatusText(latestRun)}
                {latestRunErrorNotice ? `：${latestRunErrorNotice}` : ""}
              </p>
            )}
            {closeoutReviewActivity && (
              <p aria-label="需要人工确认收口" className="error-notice" role="status">
                该任务的自动收口已用尽，需要人工确认：标记完成、改为阻塞、重新执行或补充评论。
                {` ${issueCloseoutReviewSummary(closeoutReviewActivity)}`}
              </p>
            )}
            {needsCloseoutPrompt && (
              <p aria-label="需要收尾" className="issue-action-notice" role="status">
                最新运行已成功，但任务仍未收口。若任务已经完成，请在任务阶段下拉中改成 done；否则补充 issue block 或 issue comment。
                <button
                  className="secondary small-button"
                  disabled={passiveFollowup.isPending}
                  type="button"
                  onClick={() => passiveFollowup.mutate()}
                >
                  {passiveFollowup.isPending ? "提交中" : "立即收尾跟进"}
                </button>
              </p>
            )}
            {passiveFollowup.error && <ErrorNotice error={passiveFollowup.error} />}
          </header>

          <main className="issue-detail-main">
            <p className="issue-description">{issue.data.description || "暂无描述"}</p>
            <IssueQueueStatusPanel
              activeRuns={activeAssigneeRuns}
              agentsById={agentsById}
              currentRun={latestRun}
              issue={issue.data}
              orgId={orgId}
            />

            <section aria-label="子任务" className="issue-section-card">
              <div className="issue-section-heading">
                <div>
                  <p className="eyebrow">SUBTASKS</p>
                  <h2>子任务</h2>
                </div>
                <span className="muted">{subIssueList.length}</span>
              </div>
              <form className="issue-subtask-form" onSubmit={submitSubIssue}>
                <input
                  aria-label="子任务名称"
                  placeholder="输入子任务名称"
                  value={subIssueTitle}
                  onChange={(event) => setSubIssueTitle(event.target.value)}
                />
                <button disabled={createSubIssue.isPending || !subIssueTitle.trim()} type="submit">添加子任务</button>
              </form>
              {createSubIssue.error && <ErrorNotice error={createSubIssue.error} />}
              {subIssues.isLoading && <p className="muted">加载子任务中...</p>}
              {subIssues.error && <ErrorNotice error={subIssues.error} />}
              {!subIssues.isLoading && !subIssues.error && subIssueList.length === 0 && <p className="muted">暂无子任务。</p>}
              {subIssueList.length > 0 && (
                <div className="issue-subtask-list">
                  {subIssueList.map((child) => (
                    <Link className="issue-subtask-row" key={child.id} to={`/orgs/${orgId}/issues/${child.id}`}>
                      <span className="issue-subtask-id">{child.identifier ?? child.id.slice(0, 8)}</span>
                      <strong>{child.title}</strong>
                      <span className="issue-subtask-meta">
                        <Badge>{child.status}</Badge>
                        <Badge>{child.priority}</Badge>
                      </span>
                    </Link>
                  ))}
                </div>
              )}
            </section>

            <section aria-label="评审" className="issue-section-card">
              <div className="issue-section-heading">
                <div>
                  <p className="eyebrow">REVIEW</p>
                  <h2>评审</h2>
                </div>
                <span className="muted">当前阶段：{statusLabel(issue.data.status)}</span>
              </div>
              <div className="issue-review-status">
                <div>
                  <span>Reviewer</span>
                  <strong>{issue.data.reviewerAgentId ? agentName(issue.data.reviewerAgentId, agentsById) : "未设置"}</strong>
                </div>
                <div>
                  <span>评审状态</span>
                  <strong>{["in_review", "blocked"].includes(issue.data.status) ? "等待评审结论" : "未进入评审"}</strong>
                </div>
                <p>{reviewStatusText(issue.data, agentsById)}</p>
              </div>
              <div className="actions">
                {(["approve", "request_changes", "needs_followup", "blocked"] as IssueReviewDecision[]).map((decision, index) => (
                  <button
                    aria-disabled={Boolean(reviewDecisionBlockReason(issue.data))}
                    className={`${index === 0 ? "" : "secondary"}${reviewDecisionBlockReason(issue.data) ? " is-disabled" : ""}`}
                    disabled={review.isPending}
                    key={decision}
                    onClick={() => submitReviewDecision(decision)}
                    title={reviewDecisionBlockReason(issue.data) || reviewDecisionLabel(decision)}
                    type="button"
                  >
                    {reviewDecisionLabel(decision)}
                  </button>
                ))}
                <button
                  aria-disabled={Boolean(markReviewBlockReason(issue.data))}
                  className={`secondary${markReviewBlockReason(issue.data) ? " is-disabled" : ""}`}
                  disabled={updateIssue.isPending}
                  onClick={markIssueInReview}
                  title={markReviewBlockReason(issue.data) || "将任务标记为待评审"}
                  type="button"
                >
                  标记待评审
                </button>
              </div>
              {reviewNotice && <p className="issue-action-notice" role="status">{reviewNotice}</p>}
              {review.error && <ErrorNotice error={review.error} />}
              {updateIssue.error && <ErrorNotice error={updateIssue.error} />}
            </section>

            <section aria-label="运行记录" className="issue-section-card">
              <div className="issue-section-heading">
                <div>
                  <p className="eyebrow">RUNS</p>
                  <h2>运行记录</h2>
                </div>
                <div className="issue-section-heading-actions">
                  <span className="muted">{issueRuns.data?.length ?? 0} 次运行</span>
                </div>
              </div>

              <IssueRunsPanel
                agentsById={agentsById}
                currentRunId={currentRunId}
                embedded
                expandedRunIds={expandedRunIds}
                onSelect={(runId) => {
                  localStorage.setItem(issueRunStorageKey(orgId, issueId), runId);
                  setCurrentRunId(runId);
                }}
                onToggle={(runId) => {
                  setExpandedRunIds((current) => {
                    const next = new Set(current);
                    if (next.has(runId)) {
                      next.delete(runId);
                    } else {
                      next.add(runId);
                    }
                    return next;
                  });
                }}
                renderRunDetails={(runId) => (
                  <IssueRunDetailsPanel
                    cancellingRunId={cancellingRunId}
                    issue={issue.data}
                    issueId={issueId}
                    latestRunStatus={latestRun?.status}
                    onCancelRun={(run) => cancelIssueRun.mutate(run)}
                    onRetryRun={(run) => retryRun.mutate(run)}
                    orgId={orgId}
                    retryingRunId={
                      retryRun.isPending && retryRun.variables
                        ? heartbeatRunId(retryRun.variables)
                        : undefined
                    }
                    runId={runId}
                  />
                )}
                runs={issueRuns.data ?? []}
              />
              {cancelIssueRun.error && <ErrorNotice error={cancelIssueRun.error} />}
              {retryRun.error && <ErrorNotice error={retryRun.error} />}
            </section>

            <IssueDocumentsPanel issueId={issueId} />

            <section aria-label="动态" className="issue-section-card">
              <div className="issue-section-heading">
                <div>
                  <p className="eyebrow">ACTIVITY</p>
                  <h2>动态</h2>
                </div>
                <span className="muted">
                  {comments.data?.length ?? 0} 条评论 · {attachments.data?.length ?? 0} 个文件
                </span>
              </div>
              {comments.error && <ErrorNotice error={comments.error} />}
              {issueActivity.error && <ErrorNotice error={issueActivity.error} />}
              {attachments.error && <ErrorNotice error={attachments.error} />}
              {uploadAttachment.error && <ErrorNotice error={uploadAttachment.error} />}
              {deleteAttachment.error && <ErrorNotice error={deleteAttachment.error} />}
              <section aria-label="附件" className="issue-attachments-inline">
                {uploadAttachment.isPending && attachmentFile && (
                  <p className="issue-upload-status" role="status">正在上传 {attachmentFile.name}...</p>
                )}
                {!uploadAttachment.isPending && attachmentUploadNotice && (
                  <p className="issue-upload-status success" role="status">{attachmentUploadNotice}</p>
                )}
                {attachments.isLoading && <p className="muted">加载附件中...</p>}
                {attachments.data?.length ? (
                  <div className="issue-attachment-list">
                    {attachments.data.map((attachment) => (
                      <article className="issue-attachment-item" key={attachment.id}>
                        <div className="issue-attachment-content">
                          {attachment.contentPath ? (
                            <a
                              className="issue-attachment-title"
                              href={attachment.contentPath}
                              rel="noreferrer"
                              target="_blank"
                              title={attachment.originalFilename ?? attachment.id}
                            >
                              {attachment.originalFilename ?? attachment.id}
                            </a>
                          ) : (
                            <strong>{attachment.originalFilename ?? attachment.id}</strong>
                          )}
                          <p className="muted">{attachment.contentType} · {formatBytes(attachment.byteSize)}</p>
                          {attachment.contentPath && attachment.contentType.startsWith("image/") && (
                            <a href={attachment.contentPath} rel="noreferrer" target="_blank">
                              <img
                                alt={attachment.originalFilename ?? "附件"}
                                className="issue-attachment-preview"
                                loading="lazy"
                                src={attachment.contentPath}
                              />
                            </a>
                          )}
                        </div>
                        <button
                          aria-label={`删除 ${attachment.originalFilename ?? attachment.id}`}
                          className="danger small-button"
                          disabled={deleteAttachment.isPending}
                          onClick={() => deleteAttachment.mutate(attachment.id)}
                          title="删除附件"
                          type="button"
                        >
                          删除
                        </button>
                      </article>
                    ))}
                  </div>
                ) : null}
              </section>
              <div className="issue-activity-list">
                {timelineItems.map((timelineItem) => {
                  if (timelineItem.kind === "activity") {
                    const item = timelineItem.item;
                    return (
                      <article className={`issue-activity-item tone-${activityTone(item)}`} key={timelineItem.id}>
                        <div className="issue-activity-avatar">{activityIcon(item)}</div>
                        <div className="issue-activity-content">
                          <div className="issue-activity-title-row">
                            <strong>{activityTitle(item)}</strong>
                            <span className="muted">{activityMeta(item)}</span>
                          </div>
                          <p>{activitySummary(item)}</p>
                        </div>
                      </article>
                    );
                  }
                  const item = timelineItem.item;
                  return (
                    <article className="issue-activity-item tone-comment" key={timelineItem.id}>
                      <div className="issue-activity-avatar">C</div>
                      <div className="issue-activity-content">
                        <div className="issue-activity-title-row">
                          <strong>评论</strong>
                          <span className="muted">{formatDateTime(item.createdAt)}</span>
                        </div>
                        <p>{item.body}</p>
                      </div>
                    </article>
                  );
                })}
                {comments.isSuccess && comments.data.length === 0 && (!Array.isArray(issueActivity.data) || issueActivity.data.length === 0) && (
                  <p className="muted">暂无动态。</p>
                )}
              </div>
              <form className="form issue-comment-form" onSubmit={submitComment}>
                <label>
                  添加评论
                  <textarea
                    ref={commentTextareaRef}
                    aria-controls={mentionCandidates.length ? "issue-comment-mention-list" : undefined}
                    aria-expanded={mentionCandidates.length ? "true" : "false"}
                    value={comment}
                    onChange={(event) => changeComment(event.target.value, event.target.selectionStart)}
                    onClick={(event) => updateCommentMention(event.currentTarget.value, event.currentTarget.selectionStart)}
                    onKeyDown={submitCommentFromKeyboard}
                    onKeyUp={(event) => updateCommentMention(event.currentTarget.value, event.currentTarget.selectionStart)}
                    required
                  />
                </label>
                {mentionCandidates.length > 0 && (
                  <div
                    aria-label="智能体提及候选"
                    className="issue-comment-mentions"
                    id="issue-comment-mention-list"
                    role="listbox"
                  >
                    {mentionCandidates.map((agent) => {
                      const token = agentMentionToken(agent);
                      return (
                        <button
                          aria-label={`${agent.name} @${token}`}
                          className="issue-comment-mention-option"
                          key={agent.id}
                          onClick={() => insertMention(agent)}
                          role="option"
                          type="button"
                        >
                          <strong>{agent.name}</strong>
                          <span>@{token}</span>
                        </button>
                      );
                    })}
                  </div>
                )}
                <div className="issue-comment-actions">
                  <div className="issue-attachment-menu-anchor">
                    <button
                      className="secondary small-button"
                      disabled={uploadAttachment.isPending}
                      onClick={() => setAttachmentMenuOpen((open) => !open)}
                      type="button"
                    >
                      {uploadAttachment.isPending ? "上传中..." : "添加附件"}
                    </button>
                    {attachmentMenuOpen && (
                      <div className="issue-attachment-popover" role="menu">
                        <label className="issue-attachment-popover-item">
                          上传本地文件
                          <input onChange={selectAttachment} type="file" />
                        </label>
                      </div>
                    )}
                  </div>
                  <button type="submit">发送评论</button>
                </div>
              </form>
            </section>
          </main>

          <aside className="issue-detail-sidebar">
            <div className="issue-sidebar-sticky">
              <IssuePropertiesPanel
                agents={agentList}
                goals={goalList}
                issue={issue.data}
                isUpdating={updateIssue.isPending}
                latestRunStatus={latestRun?.status}
                onUpdate={(payload) => updateIssue.mutate(payload)}
                projects={projectList}
              />
              <IssueCostPanel runs={issueRuns.data ?? []} />
              {updateIssue.error && <ErrorNotice error={updateIssue.error} />}
            </div>
          </aside>
        </div>
      )}
      {!issue.data && (
        <header className="page-header">
          <div>
            <Link className="back-link" to={`/orgs/${orgId}/issues`}>返回任务</Link>
            <h1>载入中...</h1>
          </div>
        </header>
      )}
    </IssuesWorkspace>
  );
}
