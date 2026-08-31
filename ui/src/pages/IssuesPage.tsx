import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { accessApi, authApi } from "../api/access";
import { agentsApi } from "../api/agents";
import { issuesApi } from "../api/issues";
import { projectsApi } from "../api/projects";
import type { IssuePriority, IssueStatus } from "../api/types";
import { AUTH_SESSION_STALE_TIME_MS } from "../auth/sessionCache";
import { IssuesWorkspace } from "../components/ContextWorkspace";
import { ErrorNotice } from "../components/ErrorNotice";
import { IssueStatusBoard } from "../components/IssueStatusBoard";
import { priorityLabel, statusLabel } from "../utils/display";
import { organizationMembersWithAgentFallback } from "../utils/organizationMembers";

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
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const requestedStatus = searchParams.get("status");
  const shouldOpenCreate = searchParams.get("create") === "1";
  const status = STATUSES.includes(requestedStatus as IssueStatus) ? requestedStatus as IssueStatus | "" : "";
  const projectId = searchParams.get("projectId") ?? "";
  const mineOnly = searchParams.get("mine") === "1";
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [selectedProjectId, setSelectedProjectId] = useState(projectId);
  const [assignee, setAssignee] = useState("");
  const [reviewerAgentId, setReviewerAgentId] = useState("");
  const [modelConfig, setModelConfig] = useState("default");
  const [priority, setPriority] = useState<IssuePriority>("medium");
  const [newIssueStatus, setNewIssueStatus] = useState<IssueStatus>("todo");
  const [taskDialogOpen, setTaskDialogOpen] = useState(false);
  const queryClient = useQueryClient();
  const agents = useQuery({ queryKey: ["agents", orgId], queryFn: () => agentsApi.list(orgId) });
  const hierarchy = useQuery({ queryKey: ["organization-hierarchy", orgId], queryFn: () => accessApi.hierarchy(orgId) });
  const session = useQuery({
    queryKey: ["auth-session"],
    queryFn: authApi.session,
    staleTime: AUTH_SESSION_STALE_TIME_MS,
  });
  const projects = useQuery({ queryKey: ["projects", orgId], queryFn: () => projectsApi.list(orgId) });
  const issues = useQuery({
    queryKey: ["issues", orgId, status, projectId, mineOnly, session.data?.user?.id],
    queryFn: () => issuesApi.list(orgId, {
      ...(status ? { status } : {}),
      ...(projectId ? { projectId } : {}),
      ...(mineOnly && session.data?.user?.id ? { assigneeUserId: session.data.user.id } : {}),
    }),
    enabled: !mineOnly || Boolean(session.data?.user?.id),
  });
  const create = useMutation({
    mutationFn: issuesApi.create.bind(null, orgId),
    onSuccess: () => {
      setTitle("");
      setDescription("");
      setSelectedProjectId(projectId);
      setAssignee("");
      setReviewerAgentId("");
      setModelConfig("default");
      setPriority("medium");
      setNewIssueStatus("todo");
      setTaskDialogOpen(false);
      if (shouldOpenCreate) navigate(`/orgs/${orgId}/issues`);
      void queryClient.invalidateQueries({ queryKey: ["issues", orgId] });
    },
  });
  function closeTaskDialog() {
    setTaskDialogOpen(false);
    if (shouldOpenCreate) navigate(`/orgs/${orgId}/issues`);
  }
  function submit(event: FormEvent) {
    event.preventDefault();
    if (!title.trim()) return;
    const submitter = (event.nativeEvent as SubmitEvent).submitter as HTMLButtonElement | null;
    const requestedStatus = submitter?.value === "backlog" ? "backlog" : newIssueStatus;
    create.mutate({
      title: title.trim(),
      ...(description.trim() ? { description: description.trim() } : {}),
      ...(selectedProjectId ? { projectId: selectedProjectId } : {}),
      ...(assignee.startsWith("agent:") ? { assigneeAgentId: assignee.slice(6) } : {}),
      ...(assignee.startsWith("user:") ? { assigneeUserId: assignee.slice(5) } : {}),
      ...(reviewerAgentId && reviewerAgentId !== assignee.slice(6) ? { reviewerAgentId } : {}),
      priority,
      status: requestedStatus,
    });
  }
  const agentList = Array.isArray(agents.data) ? agents.data : [];
  const memberList = Array.isArray(hierarchy.data) ? hierarchy.data : [];
  const assignableMembers = organizationMembersWithAgentFallback(memberList, agentList, orgId);
  const projectList = Array.isArray(projects.data) ? projects.data : [];
  const issueList = Array.isArray(issues.data) ? issues.data : [];
  useEffect(() => {
    if (shouldOpenCreate) {
      setSelectedProjectId(projectId);
      setTaskDialogOpen(true);
    }
  }, [projectId, shouldOpenCreate]);
  return (
    <IssuesWorkspace contentClassName="org-content-full" orgId={orgId}>
      <header className="page-header">
        <div>
          <p className="eyebrow">Issues</p>
          <h1>工作列表</h1>
          <p className="muted">查看任务分工与状态，跟进工作进度。</p>
        </div>
          <div className="org-page-actions">
            <button
              type="button"
              onClick={() => {
                setSelectedProjectId(projectId);
                setTaskDialogOpen(true);
              }}
            >
              新建任务
            </button>
          </div>
      </header>
      {agents.error && <ErrorNotice error={agents.error} />}
      {hierarchy.error && <ErrorNotice error={hierarchy.error} />}
      {projects.error && <ErrorNotice error={projects.error} />}
      {issues.error && <ErrorNotice error={issues.error} />}
      {create.error && <ErrorNotice error={create.error} />}
      <section className="panel issue-table issue-status-board">
        {issues.isLoading && <p className="muted">载入中...</p>}
        {issues.isSuccess && issueList.length === 0 && <p className="muted">暂无任务。</p>}
        <IssueStatusBoard agents={agentList} issues={issueList} members={assignableMembers} orgId={orgId} projects={projectList} />
      </section>
      {taskDialogOpen && (
        <div
          className="modal-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) closeTaskDialog();
          }}
          role="presentation"
        >
          <section aria-labelledby="new-task-title" aria-modal="true" className="panel task-modal task-create-modal" role="dialog">
            <div className="task-modal-header">
              <div>
                <h2 id="new-task-title">新建任务</h2>
                <p className="muted">配置任务信息、执行归属和优先级。</p>
              </div>
              <button aria-label="关闭" className="secondary" onClick={closeTaskDialog} type="button">关闭</button>
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
                  负责人
                  <select
                    value={assignee}
                    onChange={(event) => {
                      const nextAssignee = event.target.value;
                      setAssignee(nextAssignee);
                      if (nextAssignee === `agent:${reviewerAgentId}`) setReviewerAgentId("");
                    }}
                  >
                    <option value="">不分配</option>
                    {assignableMembers.filter((member) => member.status === "active").map((member) => (
                      <option key={member.id} value={`${member.principalType}:${member.principalId}`}>
                        {member.displayName}{member.principalType === "user" ? "（Human）" : ""}
                      </option>
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
                      <option disabled={`agent:${agent.id}` === assignee} key={agent.id} value={agent.id}>{agent.name}</option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="task-form-row">
                <label className="form-field-full">
                  模型配置
                  <select disabled={assignee.startsWith("user:")} value={modelConfig} onChange={(event) => setModelConfig(event.target.value)}>
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
                    <option value="todo">{statusLabel("todo")}</option>
                    <option value="in_progress">{statusLabel("in_progress")}</option>
                    <option value="in_review">{statusLabel("in_review")}</option>
                    <option value="blocked">{statusLabel("blocked")}</option>
                  </select>
                </label>
                <label>
                  优先级
                  <select value={priority} onChange={(event) => setPriority(event.target.value as IssuePriority)}>
                    <option value="critical">{priorityLabel("critical")}</option>
                    <option value="high">{priorityLabel("high")}</option>
                    <option value="medium">{priorityLabel("medium")}</option>
                    <option value="low">{priorityLabel("low")}</option>
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
