import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { approvalsApi } from "../api/approvals";
import { Badge } from "../components/Badge";
import { ErrorNotice } from "../components/ErrorNotice";
import { OrgWorkspace } from "./OrganizationPage";

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
  return (
    <OrgWorkspace orgId={orgId}>
      <header className="page-header">
        <div>
          <Link className="back-link" to={`/orgs/${orgId}/approvals`}>返回 Approvals</Link>
          <h1>{approval.data?.type ?? "载入中..."}</h1>
        </div>
      </header>
      {approval.data && (
        <section className="panel approval-detail">
          <div className="meta-line"><Badge>{approval.data.status}</Badge></div>
          <h2>Payload</h2>
          <pre>{JSON.stringify(approval.data.payload, null, 2)}</pre>
          <label>
            决策备注
            <textarea value={decisionNote} onChange={(event) => setDecisionNote(event.target.value)} />
          </label>
          <div className="actions">
            <button onClick={() => act.mutate("approve")} type="button">批准</button>
            <button className="secondary" onClick={() => act.mutate("requestRevision")} type="button">
              请求修改
            </button>
            <button className="danger" onClick={() => act.mutate("reject")} type="button">拒绝</button>
            {approval.data.status === "revision_requested" && (
              <button className="secondary" onClick={() => act.mutate("resubmit")} type="button">重新提交</button>
            )}
          </div>
          {act.error && <ErrorNotice error={act.error} />}
        </section>
      )}
    </OrgWorkspace>
  );
}
