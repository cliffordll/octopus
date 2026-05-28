import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { approvalsApi } from "../api/approvals";
import type { ApprovalListItem, ApprovalStatus } from "../api/types";
import { Badge } from "../components/Badge";
import { ChatsWorkspace } from "../components/ContextWorkspace";
import { ErrorNotice } from "../components/ErrorNotice";

const STATUS_OPTIONS: Array<{ value: ApprovalStatus | ""; label: string }> = [
  { value: "", label: "全部审批" },
  { value: "pending", label: "待处理" },
  { value: "revision_requested", label: "请求修改" },
  { value: "approved", label: "已同意" },
  { value: "rejected", label: "已拒绝" },
];

function approvalTitle(approval: ApprovalListItem) {
  const labels: Record<ApprovalListItem["type"], string> = {
    hire_agent: "招聘智能体",
    approve_ceo_strategy: "CEO 策略审批",
    budget_override_required: "预算覆盖审批",
    chat_issue_creation: "聊天创建任务审批",
    chat_operation: "聊天操作审批",
  };
  return labels[approval.type] ?? approval.type;
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

export function ApprovalsPage() {
  const { orgId = "" } = useParams();
  const [status, setStatus] = useState<ApprovalStatus | "">("");
  const queryClient = useQueryClient();
  const approvals = useQuery({
    queryKey: ["approvals", orgId, status],
    queryFn: () => approvalsApi.list(orgId, status || undefined),
  });
  const decision = useMutation({
    mutationFn: ({ approvalId, action }: { approvalId: string; action: "approve" | "reject" | "requestRevision" }) =>
      approvalsApi[action](approvalId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["approvals", orgId] }),
  });
  const approvalList = approvals.data ?? [];

  return (
    <ChatsWorkspace orgId={orgId}>
      <header className="page-header">
        <div>
          <p className="eyebrow">Approvals</p>
          <h1>审批管理</h1>
          <p className="muted">审批对象保留在消息上下文中处理，避免决策脱离对话。</p>
        </div>
      </header>
      <section className="approval-management">
        <div className="approval-toolbar">
          {STATUS_OPTIONS.map((option) => (
            <button
              className={status === option.value ? "active" : ""}
              key={option.value || "all"}
              onClick={() => setStatus(option.value)}
              type="button"
            >
              {option.label}
            </button>
          ))}
        </div>
        {approvals.error && <ErrorNotice error={approvals.error} />}
        {decision.error && <ErrorNotice error={decision.error} />}
        <div className="approval-thread">
          {approvalList.map((approval) => {
            const pending = approval.status === "pending";
            return (
              <article className="approval-card" key={approval.id}>
                <div className="approval-card-header">
                  <div>
                    <p className="eyebrow">Approvals assistant</p>
                    <h2>{approvalTitle(approval)}</h2>
                  </div>
                  <Badge>{approval.status}</Badge>
                </div>
                <p className="muted">
                  {approval.requestedByAgentId ? `智能体 ${approval.requestedByAgentId} 发起` : "系统或用户发起"}
                  {" · "}
                  {formatDate(approval.createdAt)}
                </p>
                <div className="approval-card-payload">
                  <span>审批类型</span>
                  <strong>{approval.type}</strong>
                </div>
                <div className="approval-actions">
                  {pending && (
                    <>
                      <button disabled={decision.isPending} onClick={() => decision.mutate({ approvalId: approval.id, action: "approve" })} type="button">
                        同意
                      </button>
                      <button className="danger" disabled={decision.isPending} onClick={() => decision.mutate({ approvalId: approval.id, action: "reject" })} type="button">
                        拒绝
                      </button>
                      <button className="secondary" disabled={decision.isPending} onClick={() => decision.mutate({ approvalId: approval.id, action: "requestRevision" })} type="button">
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
          })}
          {approvals.isSuccess && approvalList.length === 0 && (
            <section className="panel approval-empty-state">
              <p className="eyebrow">Approvals</p>
              <h2>暂无待展示审批</h2>
              <p className="muted">需要人工处理或最近更新的审批会出现在这里。</p>
            </section>
          )}
        </div>
      </section>
    </ChatsWorkspace>
  );
}
