import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { approvalsApi } from "../api/approvals";
import type { ApprovalStatus, ApprovalType } from "../api/types";
import { Badge } from "../components/Badge";
import { ErrorNotice } from "../components/ErrorNotice";
import { OrgNavigation } from "./OrganizationPage";

const TYPES: ApprovalType[] = [
  "hire_agent",
  "approve_ceo_strategy",
  "budget_override_required",
  "chat_issue_creation",
  "chat_operation",
];

export function ApprovalsPage() {
  const { orgId = "" } = useParams();
  const [status, setStatus] = useState<ApprovalStatus | "">("");
  const [type, setType] = useState<ApprovalType>(TYPES[0]);
  const [payload, setPayload] = useState("{}");
  const [payloadError, setPayloadError] = useState("");
  const queryClient = useQueryClient();
  const approvals = useQuery({
    queryKey: ["approvals", orgId, status],
    queryFn: () => approvalsApi.list(orgId, status || undefined),
  });
  const create = useMutation({
    mutationFn: (body: { type: ApprovalType; payload: Record<string, unknown> }) =>
      approvalsApi.create(orgId, body),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["approvals", orgId] }),
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    try {
      const value = JSON.parse(payload) as Record<string, unknown>;
      setPayloadError("");
      create.mutate({ type, payload: value });
    } catch {
      setPayloadError("Payload 必须是 JSON 对象");
    }
  }
  return (
    <>
      <header className="page-header">
        <div><p className="eyebrow">Approvals</p><h1>审批队列</h1></div>
        <OrgNavigation orgId={orgId} />
      </header>
      <div className="grid-two">
        <section className="panel">
          <label>
            状态筛选
            <select value={status} onChange={(event) => setStatus(event.target.value as ApprovalStatus | "")}>
              <option value="">全部</option>
              <option value="pending">pending</option>
              <option value="revision_requested">revision_requested</option>
              <option value="approved">approved</option>
              <option value="rejected">rejected</option>
            </select>
          </label>
          {approvals.error && <ErrorNotice error={approvals.error} />}
          <div className="list">
            {approvals.data?.map((approval) => (
              <article className="row" key={approval.id}>
                <Link to={`/orgs/${orgId}/approvals/${approval.id}`}>{approval.type}</Link>
                <Badge>{approval.status}</Badge>
              </article>
            ))}
          </div>
        </section>
        <form className="panel form" onSubmit={submit}>
          <h2>创建审批</h2>
          <label>
            类型
            <select value={type} onChange={(event) => setType(event.target.value as ApprovalType)}>
              {TYPES.map((item) => <option key={item}>{item}</option>)}
            </select>
          </label>
          <label>
            Payload JSON
            <textarea value={payload} onChange={(event) => setPayload(event.target.value)} />
          </label>
          {payloadError && <div className="error-notice">{payloadError}</div>}
          {create.error && <ErrorNotice error={create.error} />}
          <button type="submit">提交审批</button>
        </form>
      </div>
    </>
  );
}
