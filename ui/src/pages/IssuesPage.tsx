import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { agentsApi } from "../api/agents";
import { issuesApi } from "../api/issues";
import { projectsApi } from "../api/projects";
import type { IssuePriority, IssueStatus } from "../api/types";
import { Badge } from "../components/Badge";
import { IssuesWorkspace } from "../components/ContextWorkspace";
import { ErrorNotice } from "../components/ErrorNotice";

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

const MODEL_OPTIONS = [
  { value: "default", label: "使用智能体默认模型" },
  { value: "gpt-5", label: "GPT-5" },
  { value: "gpt-5-codex", label: "GPT-5 Codex" },
  { value: "gpt-4.1", label: "GPT-4.1" },
];

export function IssuesPage() {
  const { orgId = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedStatus = searchParams.get("status");
  const status = STATUSES.includes(requestedStatus as IssueStatus) ? requestedStatus as IssueStatus | "" : "";
  const projectId = searchParams.get("projectId") ?? "";
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [selectedProjectId, setSelectedProjectId] = useState(projectId);
  const [assigneeAgentId, setAssigneeAgentId] = useState("");
  const [reviewerAgentId, setReviewerAgentId] = useState("");
  const [modelConfig, setModelConfig] = useState("default");
  const [priority, setPriority] = useState<IssuePriority>("medium");
  const [newIssueStatus, setNewIssueStatus] = useState<IssueStatus>("todo");
  const [taskDialogOpen, setTaskDialogOpen] = useState(false);
  const queryClient = useQueryClient();
  const agents = useQuery({ queryKey: ["agents", orgId], queryFn: () => agentsApi.list(orgId) });
  const projects = useQuery({ queryKey: ["projects", orgId], queryFn: () => projectsApi.list(orgId) });
  const issues = useQuery({
    queryKey: ["issues", orgId, status, projectId],
    queryFn: () => issuesApi.list(orgId, {
      ...(status ? { status } : {}),
      ...(projectId ? { projectId } : {}),
    }),
  });
  const create = useMutation({
    mutationFn: issuesApi.create.bind(null, orgId),
    onSuccess: () => {
      setTitle("");
      setDescription("");
      setSelectedProjectId(projectId);
      setAssigneeAgentId("");
      setReviewerAgentId("");
      setModelConfig("default");
      setPriority("medium");
      setNewIssueStatus("todo");
      setTaskDialogOpen(false);
      void queryClient.invalidateQueries({ queryKey: ["issues", orgId] });
    },
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    if (!title.trim()) return;
    const submitter = (event.nativeEvent as SubmitEvent).submitter as HTMLButtonElement | null;
    const requestedStatus = submitter?.value === "backlog" ? "backlog" : newIssueStatus;
    create.mutate({
      title: title.trim(),
      ...(description.trim() ? { description: description.trim() } : {}),
      ...(selectedProjectId ? { projectId: selectedProjectId } : {}),
      ...(assigneeAgentId ? { assigneeAgentId } : {}),
      ...(reviewerAgentId ? { reviewerAgentId } : {}),
      priority,
      status: requestedStatus,
    });
  }
  const agentList = Array.isArray(agents.data) ? agents.data : [];
  const projectList = Array.isArray(projects.data) ? projects.data : [];
  return (
    <IssuesWorkspace orgId={orgId}>
      <header className="page-header">
        <div>
          <p className="eyebrow">Issues</p>
          <h1>工作列表</h1>
        </div>
          <button
            type="button"
            onClick={() => {
              setSelectedProjectId(projectId);
              setTaskDialogOpen(true);
            }}
          >
            新建任务
          </button>
      </header>
      <div className="toolbar">
        <label>
          状态筛选
          <select
            value={status}
            onChange={(event) => {
              const nextStatus = event.target.value;
              setSearchParams({
                ...(nextStatus ? { status: nextStatus } : {}),
                ...(projectId ? { projectId } : {}),
              });
            }}
          >
            {STATUSES.map((item) => (
              <option key={item || "all"} value={item}>
                {item || "全部"}
              </option>
            ))}
          </select>
        </label>
      </div>
      {agents.error && <ErrorNotice error={agents.error} />}
      {projects.error && <ErrorNotice error={projects.error} />}
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
      {taskDialogOpen && (
        <div
          className="modal-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setTaskDialogOpen(false);
          }}
          role="presentation"
        >
          <section aria-labelledby="new-task-title" aria-modal="true" className="panel task-modal task-create-modal" role="dialog">
            <div className="task-modal-header">
              <div>
                <h2 id="new-task-title">新建任务</h2>
                <p className="muted">配置任务信息、执行归属和优先级。</p>
              </div>
              <button aria-label="关闭" className="secondary" onClick={() => setTaskDialogOpen(false)} type="button">关闭</button>
            </div>
            <form className="form task-create-form" onSubmit={submit}>
              <div className="task-form-row">
                <label className="form-field-full">
                  任务名称
                  <input autoFocus value={title} onChange={(event) => setTitle(event.target.value)} required />
                </label>
              </div>
              <div className="task-form-row task-form-grid task-form-grid-three">
                <label>
                  智能体
                  <select value={assigneeAgentId} onChange={(event) => setAssigneeAgentId(event.target.value)}>
                    <option value="">不分配</option>
                    {agentList.map((agent) => (
                      <option key={agent.id} value={agent.id}>{agent.name}</option>
                    ))}
                  </select>
                </label>
                <label>
                  项目
                  <select value={selectedProjectId} onChange={(event) => setSelectedProjectId(event.target.value)}>
                    <option value="">不关联项目</option>
                    {projectList.map((project) => (
                      <option key={project.id} value={project.id}>{project.name}</option>
                    ))}
                  </select>
                </label>
                <label>
                  Reviewer
                  <select value={reviewerAgentId} onChange={(event) => setReviewerAgentId(event.target.value)}>
                    <option value="">不设置</option>
                    {agentList.map((agent) => (
                      <option key={agent.id} value={agent.id}>{agent.name}</option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="task-form-row">
                <label className="form-field-full">
                  模型配置
                  <select value={modelConfig} onChange={(event) => setModelConfig(event.target.value)}>
                    {MODEL_OPTIONS.map((model) => (
                      <option key={model.value} value={model.value}>{model.label}</option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="task-form-row">
                <label className="form-field-full">
                  描述
                  <textarea value={description} onChange={(event) => setDescription(event.target.value)} />
                </label>
              </div>
              <div className="task-form-row task-form-grid">
                <label>
                  代办
                  <select value={newIssueStatus} onChange={(event) => setNewIssueStatus(event.target.value as IssueStatus)}>
                    <option value="todo">todo</option>
                    <option value="in_progress">in_progress</option>
                    <option value="in_review">in_review</option>
                    <option value="blocked">blocked</option>
                  </select>
                </label>
                <label>
                  优先级
                  <select value={priority} onChange={(event) => setPriority(event.target.value as IssuePriority)}>
                    <option value="critical">critical</option>
                    <option value="high">high</option>
                    <option value="medium">medium</option>
                    <option value="low">low</option>
                  </select>
                </label>
              </div>
              <div className="task-modal-actions">
                <button
                  className="secondary"
                  disabled={create.isPending}
                  type="submit"
                  value="backlog"
                >
                  保存草稿
                </button>
                <button
                  disabled={create.isPending}
                  type="submit"
                  value={newIssueStatus}
                >
                  创建任务
                </button>
              </div>
            </form>
          </section>
        </div>
      )}
    </IssuesWorkspace>
  );
}
