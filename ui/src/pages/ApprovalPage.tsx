import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { approvalsApi } from "../api/approvals";
import { Badge } from "../components/Badge";
import { ChatsWorkspace } from "../components/ContextWorkspace";
import { ErrorNotice } from "../components/ErrorNotice";

export function ApprovalPage() {
  const { orgId = "", approvalId = "" } = useParams();
  const [decisionNote, setDecisionNote] = useState("");
  const queryClient = useQueryClient();
  const approval = useQuery({
    queryKey: ["approval", approvalId],
    queryFn: () => approvalsApi.get(approvalId),
  });
  const act = useMutation({
    mutationFn: (action: "approve" | "reject" | "requestRevision" | "resubmit") => {
      if (action === "resubmit") return approvalsApi.resubmit(approvalId, {});
      return approvalsApi[action](approvalId, decisionNote.trim() || undefined);
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["approval", approvalId] }),
  });
  if (approval.error) return <ErrorNotice error={approval.error} />;
  const isActionable = approval.data?.status === "pending";
  return (
    <ChatsWorkspace orgId={orgId}>
      <header className="page-header">
        <div>
          <Link className="back-link" to={`/orgs/${orgId}/approvals`}>返回审批管理</Link>
          <p className="eyebrow">Approval</p>
          <h1>{approval.data?.type ?? "载入中..."}</h1>
          <p className="muted">在消息上下文中查看完整请求并做出决策。</p>
        </div>
      </header>
      {approval.data && (
        <section className="approval-detail-layout">
          <article className="panel approval-detail">
            <div className="approval-card-header">
              <div>
                <p className="eyebrow">审批对象</p>
                <h2>{approval.data.type}</h2>
              </div>
              <Badge>{approval.data.status}</Badge>
            </div>
            <dl className="detail-grid">
              <div>
                <dt>审批 ID</dt>
                <dd>{approval.data.id}</dd>
              </div>
              <div>
                <dt>发起时间</dt>
                <dd>{approval.data.createdAt || "未知"}</dd>
              </div>
              <div>
                <dt>发起智能体</dt>
                <dd>{approval.data.requestedByAgentId ?? "无"}</dd>
              </div>
              <div>
                <dt>决策人</dt>
                <dd>{approval.data.decidedByUserId ?? "未决策"}</dd>
              </div>
            </dl>
            {approval.data.decisionNote && (
              <div className="approval-note">
                <span>Decision note</span>
                <p>{approval.data.decisionNote}</p>
              </div>
            )}
            <h3>完整请求</h3>
            <pre>{JSON.stringify(approval.data.payload, null, 2)}</pre>
          </article>
          <aside className="panel approval-decision-panel">
            <h2>审批决策</h2>
            {isActionable ? (
              <>
                <label>
                  决策备注
                  <textarea
                    placeholder="可选：说明同意、拒绝或请求修改的原因。"
                    value={decisionNote}
                    onChange={(event) => setDecisionNote(event.target.value)}
                  />
                </label>
                <div className="actions">
                  <button disabled={act.isPending} onClick={() => act.mutate("approve")} type="button">同意</button>
                  <button className="danger" disabled={act.isPending} onClick={() => act.mutate("reject")} type="button">拒绝</button>
                  <button className="secondary" disabled={act.isPending} onClick={() => act.mutate("requestRevision")} type="button">
                    请求修改
                  </button>
                </div>
              </>
            ) : (
              <p className="muted">该审批已处理，当前状态为 {approval.data.status}。</p>
            )}
            {approval.data.status === "revision_requested" && (
              <button className="secondary" disabled={act.isPending} onClick={() => act.mutate("resubmit")} type="button">标记重新提交</button>
            )}
          </aside>
          {act.error && <ErrorNotice error={act.error} />}
        </section>
      )}
    </ChatsWorkspace>
  );
}
