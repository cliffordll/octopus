import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { agentsApi } from "../api/agents";
import { approvalsApi } from "../api/approvals";
import { messengerApi } from "../api/messenger";
import type { ApprovalDetail, ApprovalListItem, ApprovalStatus } from "../api/types";
import { Badge } from "../components/Badge";
import { ChatsWorkspace } from "../components/ContextWorkspace";
import { ErrorNotice } from "../components/ErrorNotice";
import { statusLabel } from "../utils/display";

const STATUS_OPTIONS: Array<{ value: ApprovalStatus; label: string }> = [
  { value: "pending", label: "待审批" },
  { value: "revision_requested", label: "需修改" },
  { value: "approved", label: "已同意" },
  { value: "rejected", label: "已拒绝" },
];

function approvalTitle(approval: ApprovalListItem) {
  return approval.type;
}

function proposedIssueTitle(approval?: ApprovalDetail | null): string | null {
  const proposedIssue = approval?.payload?.proposedIssue;
  if (!proposedIssue || typeof proposedIssue !== "object" || Array.isArray(proposedIssue)) return null;
  const title = (proposedIssue as Record<string, unknown>).title;
  return typeof title === "string" && title.trim() ? title.trim() : null;
}

function approvalFromMessengerItem(item: Record<string, unknown>): ApprovalDetail | null {
  const approval = item.approval;
  return approval && typeof approval === "object" && !Array.isArray(approval)
    ? approval as ApprovalDetail
    : null;
}

function formatDate(value: string) {
  if (!value) return "未知时间";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function parseJsonObject(value: string): Record<string, unknown> {
  const parsed: unknown = JSON.parse(value);
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error("审批 payload 必须是 JSON 对象");
  }
  return parsed as Record<string, unknown>;
}

function createApprovalErrorMessage(error: unknown): string {
  const message = error instanceof Error ? error.message : "";
  if (/one or more issues not found/i.test(message)) {
    return "一个或多个任务不存在。请检查任务 ID 后重试。";
  }
  return message || "创建审批失败";
}

export function ApprovalsPage() {
  const { orgId = "" } = useParams();
  const [status, setStatus] = useState<ApprovalStatus | "">("");
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [approvalType, setApprovalType] = useState<ApprovalListItem["type"]>("chat_operation");
  const [approvalPayload, setApprovalPayload] = useState("{}");
  const [requestedByAgentId, setRequestedByAgentId] = useState("");
  const [issueIds, setIssueIds] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const approvals = useQuery({
    queryKey: ["messenger-approvals", orgId],
    queryFn: () => messengerApi.approvals(orgId),
  });
  const agents = useQuery({
    queryKey: ["agents", orgId],
    queryFn: () => agentsApi.list(orgId),
  });
  const decision = useMutation({
    mutationFn: ({ approvalId, action }: { approvalId: string; action: "approve" | "reject" | "requestRevision" }) =>
      approvalsApi[action](approvalId),
    onSuccess: (approval) => {
      void queryClient.invalidateQueries({ queryKey: ["messenger-approvals", orgId] });
      void queryClient.invalidateQueries({ queryKey: ["approvals", orgId] });
      void queryClient.invalidateQueries({ queryKey: ["approval", approval.id] });
      void queryClient.invalidateQueries({ queryKey: ["approval-issues", approval.id] });
      void queryClient.invalidateQueries({ queryKey: ["issues", orgId] });
      void queryClient.invalidateQueries({ queryKey: ["issue"] });
    },
  });
  const createApproval = useMutation({
    mutationFn: () =>
      approvalsApi.create(orgId, {
        type: approvalType,
        payload: parseJsonObject(approvalPayload),
        ...(requestedByAgentId.trim() ? { requestedByAgentId: requestedByAgentId.trim() } : {}),
        ...(issueIds.trim()
          ? { issueIds: issueIds.split(",").map((item) => item.trim()).filter(Boolean) }
          : {}),
      }),
    onSuccess: () => {
      setCreateDialogOpen(false);
      setApprovalPayload("{}");
      setRequestedByAgentId("");
      setIssueIds("");
      setCreateError(null);
      void queryClient.invalidateQueries({ queryKey: ["messenger-approvals", orgId] });
      void queryClient.invalidateQueries({ queryKey: ["approvals", orgId] });
    },
    onError: (error) => setCreateError(createApprovalErrorMessage(error)),
  });
  const approvalList = (approvals.data?.detail.items ?? [])
    .map(approvalFromMessengerItem)
    .filter((approval): approval is ApprovalDetail => Boolean(approval))
    .filter((approval) => !status || approval.status === status);
  const agentList = agents.data ?? [];
  function submitApproval(event: FormEvent) {
    event.preventDefault();
    setCreateError(null);
    createApproval.mutate();
  }

  return (
    <ChatsWorkspace contentClassName="org-content-full" orgId={orgId}>
      <header className="page-header">
        <div>
          <p className="eyebrow">Approvals</p>
          <h1>审批管理</h1>
          <p className="muted">审批对象保留在消息上下文中处理，避免决策脱离对话。</p>
        </div>
      </header>
      <section className="approval-management">
        <div className="approval-toolbar">
          <button className={status === "" ? "secondary active" : "secondary"} onClick={() => setStatus("")} type="button">全部</button>
          <div aria-label="审批状态筛选" className="approval-status-filter" role="group">
            {STATUS_OPTIONS.map((option) => (
              <button
                className={status === option.value ? "active" : ""}
                key={option.value}
                onClick={() => setStatus(status === option.value ? "" : option.value)}
                type="button"
              >
                {option.label}
              </button>
            ))}
          </div>
          <button className="secondary" onClick={() => setCreateDialogOpen(true)} type="button">创建审批</button>
        </div>
        {approvals.error && <ErrorNotice error={approvals.error} />}
        {decision.error && <ErrorNotice error={decision.error} />}
        <div className="approval-thread">
          {approvalList.map((approval) => (
            <ApprovalCard
              approval={approval}
              decisionPending={decision.isPending}
              key={approval.id}
              onDecision={(action) => decision.mutate({ approvalId: approval.id, action })}
              orgId={orgId}
            />
          ))}
          {approvals.isSuccess && approvalList.length === 0 && (
            <section className="panel approval-empty-state">
              <p className="eyebrow">Approvals</p>
              <h2>暂无待展示审批</h2>
              <p className="muted">需要人工处理或最近更新的审批会出现在这里。</p>
            </section>
          )}
        </div>
      </section>
      {createDialogOpen && (
        <div aria-modal="true" className="modal-backdrop" role="dialog">
          <section className="panel task-modal">
            <div className="task-modal-header">
              <h2>创建审批</h2>
              <button className="secondary" onClick={() => setCreateDialogOpen(false)} type="button">关闭</button>
            </div>
            <form className="form" onSubmit={submitApproval}>
              <label>
                审批类型
                <select value={approvalType} onChange={(event) => setApprovalType(event.target.value as ApprovalListItem["type"])}>
                  <option value="hire_agent">hire_agent</option>
                  <option value="approve_ceo_strategy">approve_ceo_strategy</option>
                  <option value="budget_override_required">budget_override_required</option>
                  <option value="chat_issue_creation">chat_issue_creation</option>
                  <option value="chat_operation">chat_operation</option>
                </select>
              </label>
              <label>
                Payload JSON
                <textarea value={approvalPayload} onChange={(event) => setApprovalPayload(event.target.value)} />
              </label>
              <label>
                发起智能体
                <select value={requestedByAgentId} onChange={(event) => setRequestedByAgentId(event.target.value)}>
                  <option value="">无</option>
                  {agentList.map((agent) => (
                    <option key={agent.id} value={agent.id}>
                      {agent.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                任务 ID
                <input value={issueIds} onChange={(event) => setIssueIds(event.target.value)} />
              </label>
              {createError && <p className="error-notice">{createError}</p>}
              <div className="task-modal-actions">
                <button className="secondary" onClick={() => setCreateDialogOpen(false)} type="button">取消</button>
                <button disabled={createApproval.isPending} type="submit">创建</button>
              </div>
            </form>
          </section>
        </div>
      )}
    </ChatsWorkspace>
  );
}

function ApprovalCard({
  approval,
  decisionPending,
  onDecision,
  orgId,
}: {
  approval: ApprovalDetail;
  decisionPending: boolean;
  onDecision: (action: "approve" | "reject" | "requestRevision") => void;
  orgId: string;
}) {
  const issueTitle = proposedIssueTitle(approval);
  const pending = approval.status === "pending";
  return (
    <article className="approval-card">
      <div className="approval-card-header">
        <div>
          <p className="eyebrow">Approvals assistant</p>
          <h2>{issueTitle ?? approvalTitle(approval)}</h2>
          {issueTitle && <p className="approval-card-subtitle">{approval.type}</p>}
        </div>
        <Badge>{statusLabel(approval.status)}</Badge>
      </div>
      <p className="muted">
        {approval.requestedByAgentId ? `智能体 ${approval.requestedByAgentId} 发起` : "系统或用户发起"}
        {" · "}
        {formatDate(approval.createdAt)}
      </p>
      <div className="approval-card-payload">
        <span>{issueTitle ? "任务标题" : "审批类型"}</span>
        <strong>{issueTitle ?? approval.type}</strong>
      </div>
      <div className="approval-actions">
        {pending && (
          <>
            <button disabled={decisionPending} onClick={() => onDecision("approve")} type="button">
              同意
            </button>
            <button className="danger" disabled={decisionPending} onClick={() => onDecision("reject")} type="button">
              拒绝
            </button>
            <button className="secondary" disabled={decisionPending} onClick={() => onDecision("requestRevision")} type="button">
              请求修改
            </button>
          </>
        )}
        <Link className="button secondary small-button" to={`/orgs/${orgId}/approvals/${approval.id}`}>
          打开完整审批
        </Link>
      </div>
    </article>
  );
}
