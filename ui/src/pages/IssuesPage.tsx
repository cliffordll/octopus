import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { issuesApi } from "../api/issues";
import type { IssueStatus } from "../api/types";
import { Badge } from "../components/Badge";
import { ErrorNotice } from "../components/ErrorNotice";
import { OrgNavigation } from "./OrganizationPage";

const STATUSES: Array<IssueStatus | ""> = [
  "",
  "backlog",
  "todo",
  "in_progress",
  "in_review",
  "done",
  "blocked",
  "cancelled",
];

export function IssuesPage() {
  const { orgId = "" } = useParams();
  const [status, setStatus] = useState<IssueStatus | "">("");
  const [title, setTitle] = useState("");
  const queryClient = useQueryClient();
  const issues = useQuery({
    queryKey: ["issues", orgId, status],
    queryFn: () => issuesApi.list(orgId, status ? { status } : {}),
  });
  const create = useMutation({
    mutationFn: issuesApi.create.bind(null, orgId),
    onSuccess: () => {
      setTitle("");
      void queryClient.invalidateQueries({ queryKey: ["issues", orgId] });
    },
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    if (title.trim()) create.mutate({ title: title.trim() });
  }
  return (
    <>
      <header className="page-header">
        <div>
          <p className="eyebrow">Issues</p>
          <h1>工作列表</h1>
        </div>
        <OrgNavigation orgId={orgId} />
      </header>
      <div className="toolbar">
        <label>
          状态筛选
          <select value={status} onChange={(event) => setStatus(event.target.value as IssueStatus | "")}>
            {STATUSES.map((item) => (
              <option key={item || "all"} value={item}>
                {item || "全部"}
              </option>
            ))}
          </select>
        </label>
        <form className="inline-create" onSubmit={submit}>
          <label>
            Issue 标题
            <input value={title} onChange={(event) => setTitle(event.target.value)} required />
          </label>
          <button type="submit">新建 Issue</button>
        </form>
      </div>
      {issues.error && <ErrorNotice error={issues.error} />}
      {create.error && <ErrorNotice error={create.error} />}
      <section className="panel issue-table">
        {issues.isLoading && <p className="muted">载入中...</p>}
        {issues.data?.map((issue) => (
          <article className="issue-row" key={issue.id}>
            <span className="identifier">{issue.identifier ?? "-"}</span>
            <Link to={`/orgs/${orgId}/issues/${issue.id}`}>{issue.title}</Link>
            <Badge>{issue.priority}</Badge>
            <Badge>{issue.status}</Badge>
          </article>
        ))}
      </section>
    </>
  );
}
