import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { Link, NavLink, useNavigate, useParams } from "react-router-dom";
import { agentsApi } from "../api/agents";
import { issuesApi } from "../api/issues";
import { projectsApi } from "../api/projects";
import type { ProjectCodebase, ProjectResourceRole, ProjectStatus, ProjectWorkspace } from "../api/types";
import { Badge } from "../components/Badge";
import { ErrorNotice } from "../components/ErrorNotice";
import { IssueStatusBoard } from "../components/IssueStatusBoard";
import { OrgWorkspace } from "./OrganizationPage";

const STATUSES: ProjectStatus[] = ["backlog", "planned", "in_progress", "completed", "cancelled"];
const ROLES: ProjectResourceRole[] = [
  "working_set",
  "reference",
  "tracking",
  "deliverable",
  "background",
];

function formatJson(value: Record<string, unknown> | null | undefined): string {
  return value ? JSON.stringify(value, null, 2) : "";
}

function parseJsonObject(value: string): Record<string, unknown> | null {
  if (!value.trim()) return null;
  const parsed: unknown = JSON.parse(value);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("执行工作区策略必须是 JSON 对象。");
  }
  return parsed as Record<string, unknown>;
}

function nullableText(value: string | null | undefined): string {
  return value && value.trim() ? value : "未设置";
}

function ProjectCodebasePanel({ codebase, workspaces }: { codebase?: ProjectCodebase; workspaces: ProjectWorkspace[] }) {
  return (
    <section className="project-workspace-grid" aria-label="项目工作区">
      <article className="project-workspace-card">
        <div className="project-workspace-card-heading">
          <h3>代码库</h3>
          {codebase?.configured ? <Badge>已配置</Badge> : <Badge>未配置</Badge>}
        </div>
        <dl className="project-workspace-properties">
          <div><dt>来源</dt><dd>{codebase?.origin ?? "未设置"}</dd></div>
          <div><dt>仓库</dt><dd>{nullableText(codebase?.repoUrl)}</dd></div>
          <div><dt>分支</dt><dd>{nullableText(codebase?.repoRef ?? codebase?.defaultRef)}</dd></div>
          <div><dt>本地目录</dt><dd>{nullableText(codebase?.effectiveLocalFolder ?? codebase?.localFolder)}</dd></div>
        </dl>
      </article>
      <article className="project-workspace-card">
        <div className="project-workspace-card-heading">
          <h3>工作区</h3>
          <Badge>{workspaces.length}</Badge>
        </div>
        <div className="project-workspace-list">
          {workspaces.map((workspace) => (
            <div className="project-workspace-item" key={workspace.id}>
              <div>
                <strong>{workspace.name}</strong>
                <span>{nullableText(workspace.cwd)}</span>
              </div>
              <div className="project-workspace-badges">
                {workspace.isPrimary && <Badge>主工作区</Badge>}
                <Badge>{workspace.sourceType}</Badge>
                {workspace.sharedWorkspaceKey && <Badge>{workspace.sharedWorkspaceKey}</Badge>}
              </div>
            </div>
          ))}
        </div>
      </article>
    </section>
  );
}

export function ProjectPage() {
  const { orgId = "", projectId = "", tab = "configuration" } = useParams();
  const activeTab = ["configuration", "resources", "issues"].includes(tab) ? tab : "configuration";
  const [projectName, setProjectName] = useState("");
  const [description, setDescription] = useState("");
  const [status, setStatus] = useState<ProjectStatus>("backlog");
  const [leadAgentId, setLeadAgentId] = useState("");
  const [targetDate, setTargetDate] = useState("");
  const [goalIds, setGoalIds] = useState("");
  const [workspacePolicy, setWorkspacePolicy] = useState("");
  const [workspacePolicyError, setWorkspacePolicyError] = useState("");
  const [resourceId, setResourceId] = useState("");
  const [role, setRole] = useState<ProjectResourceRole>("working_set");
  const [sortOrder, setSortOrder] = useState("");
  const [editingResourceId, setEditingResourceId] = useState("");
  const [editingRole, setEditingRole] = useState<ProjectResourceRole>("working_set");
  const [editingNote, setEditingNote] = useState("");
  const [editingSortOrder, setEditingSortOrder] = useState("");
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const project = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => projectsApi.get(projectId),
  });
  const resources = useQuery({
    queryKey: ["project-resources", projectId],
    queryFn: () => projectsApi.listResources(projectId),
    enabled: activeTab === "resources",
  });
  const issues = useQuery({
    queryKey: ["issues", orgId, "project", projectId],
    queryFn: () => issuesApi.list(orgId, { projectId }),
    enabled: activeTab === "issues",
  });
  const agents = useQuery({
    queryKey: ["agents", orgId],
    queryFn: () => agentsApi.list(orgId),
    enabled: activeTab === "configuration" || activeTab === "issues",
  });
  useEffect(() => {
    if (project.data) {
      setProjectName(project.data.name);
      setDescription(project.data.description ?? "");
      setStatus(project.data.status);
      setLeadAgentId(project.data.leadAgentId ?? "");
      setTargetDate(project.data.targetDate ?? "");
      setGoalIds((project.data.goalIds ?? (project.data.goalId ? [project.data.goalId] : [])).join(","));
      setWorkspacePolicy(formatJson(project.data.executionWorkspacePolicy));
      setWorkspacePolicyError("");
    }
  }, [project.data]);
  const update = useMutation({
    mutationFn: () => {
      const executionWorkspacePolicy = parseJsonObject(workspacePolicy);
      return projectsApi.update(projectId, {
        description: description.trim() || null,
        name: projectName.trim() || project.data?.name,
        status,
        leadAgentId: leadAgentId || null,
        targetDate: targetDate || null,
        goalIds: goalIds
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
        executionWorkspacePolicy,
      });
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["project", projectId] }),
    onError: (error) => {
      if (error instanceof Error) setWorkspacePolicyError(error.message);
    },
  });
  const addResource = useMutation({
    mutationFn: () =>
      projectsApi.addResource(projectId, {
        resourceId: resourceId.trim(),
        role,
        ...(sortOrder.trim() ? { sortOrder: Number(sortOrder) } : {}),
      }),
    onSuccess: () => {
      setResourceId("");
      setSortOrder("");
      void queryClient.invalidateQueries({ queryKey: ["project-resources", projectId] });
    },
  });
  const removeResource = useMutation({
    mutationFn: (attachmentId: string) => projectsApi.removeResource(projectId, attachmentId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["project-resources", projectId] }),
  });
  const updateResource = useMutation({
    mutationFn: () =>
      projectsApi.updateResource(projectId, editingResourceId, {
        role: editingRole,
        note: editingNote.trim() || null,
        ...(editingSortOrder.trim() ? { sortOrder: Number(editingSortOrder) } : {}),
      }),
    onSuccess: () => {
      setEditingResourceId("");
      void queryClient.invalidateQueries({ queryKey: ["project-resources", projectId] });
    },
  });
  const removeProject = useMutation({
    mutationFn: () => projectsApi.remove(projectId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["projects", orgId] });
      navigate(`/orgs/${orgId}/projects`);
    },
  });
  function save(event: FormEvent) {
    event.preventDefault();
    setWorkspacePolicyError("");
    update.mutate();
  }
  function attach(event: FormEvent) {
    event.preventDefault();
    if (resourceId.trim()) addResource.mutate();
  }
  function startResourceEdit(attachment: { id: string; role: ProjectResourceRole; note: string | null; sortOrder: number }) {
    setEditingResourceId(attachment.id);
    setEditingRole(attachment.role);
    setEditingNote(attachment.note ?? "");
    setEditingSortOrder(String(attachment.sortOrder ?? ""));
  }
  function submitResourceEdit(event: FormEvent) {
    event.preventDefault();
    if (editingResourceId) updateResource.mutate();
  }
  const projectIssues = issues.data ?? [];
  const agentList = Array.isArray(agents.data) ? agents.data : [];
  if (project.error) return <ErrorNotice error={project.error} />;
  return (
    <OrgWorkspace orgId={orgId}>
      <div className="project-detail-shell">
      <header className="page-header project-detail-header">
        <div className="project-header-identity">
          <span className="project-avatar-lg" style={{ background: project.data?.color ?? "#6366f1" }}>
            {(project.data?.name ?? "P").slice(0, 1).toUpperCase()}
          </span>
          <div className="project-detail-title">
            <Link className="back-link" to={`/orgs/${orgId}/projects`}>返回项目列表</Link>
            <div className="project-heading-row">
              <h1>{project.data?.name ?? "载入中..."}</h1>
            </div>
            {project.data && (
              <div className="project-header-meta">
                <Badge>{project.data.urlKey}</Badge>
              </div>
            )}
            {project.data?.description && <p className="muted">{project.data.description}</p>}
          </div>
        </div>
        {project.data && (
          <div className="project-header-actions">
            <Link className="button secondary" to={`/orgs/${orgId}/chats`}>聊天</Link>
            <button className="danger" disabled={removeProject.isPending} onClick={() => removeProject.mutate()} type="button">删除项目</button>
          </div>
        )}
      </header>
      {project.data && (
        <>
          {project.data.pauseReason === "budget" && (
            <div className="project-budget-stop">
              <span />
              因预算硬限制暂停
            </div>
          )}
          <nav aria-label="项目详情导航" className="detail-tabs">
            <NavLink to={`/orgs/${orgId}/projects/${projectId}/configuration`}>配置</NavLink>
            <NavLink to={`/orgs/${orgId}/projects/${projectId}/resources`}>资源</NavLink>
            <NavLink to={`/orgs/${orgId}/projects/${projectId}/issues`}>任务</NavLink>
          </nav>
          {activeTab === "configuration" && <form className="panel project-properties-card project-tab-panel" onSubmit={save}>
            <div className="panel-heading">
              <div>
                <h2>配置</h2>
                <p className="muted">配置项目属性、负责人、目标日期和关联目标。</p>
              </div>
            </div>
            <div className="project-property-list">
              <label className="project-property-row">
                <span>项目名称</span>
                <input value={projectName} onChange={(event) => setProjectName(event.target.value)} required />
              </label>
              <label className="project-property-row project-property-row-start">
                <span>描述</span>
                <textarea value={description} onChange={(event) => setDescription(event.target.value)} />
              </label>
              <label className="project-property-row">
                <span>状态</span>
                <select value={status} onChange={(event) => setStatus(event.target.value as ProjectStatus)}>
                  {STATUSES.map((item) => <option key={item}>{item}</option>)}
                </select>
              </label>
              <label className="project-property-row">
                <span>负责人</span>
                <select value={leadAgentId} onChange={(event) => setLeadAgentId(event.target.value)}>
                  <option value="">未设置</option>
                  {agentList.map((agent) => (
                    <option key={agent.id} value={agent.id}>
                      {agent.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="project-property-row">
                <span>目标日期</span>
                <input type="date" value={targetDate} onChange={(event) => setTargetDate(event.target.value)} />
              </label>
              <label className="project-property-row">
                <span>目标 ID</span>
                <input value={goalIds} onChange={(event) => setGoalIds(event.target.value)} />
              </label>
              <div className="project-property-row">
                <span>URL 标识</span>
                <strong>{project.data.urlKey}</strong>
              </div>
              <div className="project-property-row">
                <span>负责人</span>
                <strong>{project.data.leadAgentId ?? "未设置"}</strong>
              </div>
              <div className="project-property-row">
                <span>目标</span>
                <div className="project-goal-chips">
                  {(project.data.goals ?? []).map((goal) => <Badge key={goal.id}>{goal.title}</Badge>)}
                  {(project.data.goals ?? []).length === 0 && project.data.goalId && <Badge>{project.data.goalId}</Badge>}
                  {(project.data.goals ?? []).length === 0 && !project.data.goalId && <span className="muted">暂无关联目标</span>}
                </div>
              </div>
              <div className="project-property-row">
                <span>创建时间</span>
                <strong>{project.data.createdAt || "-"}</strong>
              </div>
              <div className="project-property-row">
                <span>更新时间</span>
                <strong>{project.data.updatedAt || "-"}</strong>
              </div>
              <label className="project-property-row project-property-row-start">
                <span>执行工作区策略 JSON</span>
                <textarea
                  className="config-editor"
                  value={workspacePolicy}
                  onChange={(event) => setWorkspacePolicy(event.target.value)}
                  placeholder='{"enabled":true,"defaultMode":"shared_workspace"}'
                />
              </label>
            </div>
            <ProjectCodebasePanel codebase={project.data.codebase} workspaces={project.data.workspaces ?? []} />
            {workspacePolicyError && <p className="error-notice">{workspacePolicyError}</p>}
            {update.error && <ErrorNotice error={update.error} />}
            {removeProject.error && <ErrorNotice error={removeProject.error} />}
            <div className="project-property-actions">
              <button type="submit">保存项目</button>
            </div>
          </form>}
          {activeTab === "resources" && <section className="panel project-resources project-tab-panel-wide">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">项目上下文</p>
                <h2>资源</h2>
                <p className="muted">为项目关联智能体需要使用的资源，资源目录仍由组织统一维护。</p>
              </div>
            </div>
            {resources.error && <ErrorNotice error={resources.error} />}
            {updateResource.error && <ErrorNotice error={updateResource.error} />}
            <div className="project-resource-summary">
              {ROLES.map((item) => (
                <div className="summary-metric" key={item}>
                  <span>{item}</span>
                  <strong>{resources.data?.filter((attachment) => attachment.role === item).length ?? 0}</strong>
                </div>
              ))}
            </div>
            <div className="project-resource-grid">
              {resources.data?.map((attachment) => (
                <article className="project-resource-card" key={attachment.id}>
                  <div>
                    <strong>{attachment.resource.name}</strong>
                    <span>{attachment.resource.locator}</span>
                    {attachment.note && <p>{attachment.note}</p>}
                  </div>
                  <Badge>{attachment.role}</Badge>
                  <button
                    className="secondary small-button"
                    onClick={() => startResourceEdit(attachment)}
                    type="button"
                  >
                    编辑
                  </button>
                  <button
                    className="secondary small-button"
                    onClick={() => removeResource.mutate(attachment.id)}
                    type="button"
                  >
                    移除
                  </button>
                </article>
              ))}
              {resources.isSuccess && resources.data.length === 0 && <p className="muted">暂无关联资源。</p>}
            </div>
            {editingResourceId && (
              <form className="form resource-form" onSubmit={submitResourceEdit}>
                <label>
                  角色
                  <select value={editingRole} onChange={(event) => setEditingRole(event.target.value as ProjectResourceRole)}>
                    {ROLES.map((item) => <option key={item}>{item}</option>)}
                  </select>
                </label>
                <label>
                  备注
                  <input value={editingNote} onChange={(event) => setEditingNote(event.target.value)} />
                </label>
                <label>
                  排序
                  <input
                    min="0"
                    type="number"
                    value={editingSortOrder}
                    onChange={(event) => setEditingSortOrder(event.target.value)}
                  />
                </label>
                <button className="secondary" onClick={() => setEditingResourceId("")} type="button">取消</button>
                <button disabled={updateResource.isPending} type="submit">保存资源</button>
              </form>
            )}
            <form className="form resource-form" onSubmit={attach}>
              <label>
                资源 ID
                <input value={resourceId} onChange={(event) => setResourceId(event.target.value)} required />
              </label>
              <label>
                角色
                <select value={role} onChange={(event) => setRole(event.target.value as ProjectResourceRole)}>
                  {ROLES.map((item) => <option key={item}>{item}</option>)}
                </select>
              </label>
              <label>
                排序
                <input
                  min="0"
                  type="number"
                  value={sortOrder}
                  onChange={(event) => setSortOrder(event.target.value)}
                />
              </label>
              {addResource.error && <ErrorNotice error={addResource.error} />}
              <button type="submit">添加资源</button>
            </form>
          </section>}
          {activeTab === "issues" && <section className="panel project-issues project-tab-panel-wide">
            <div className="panel-heading">
              <div>
                <h2>任务</h2>
                <p className="muted">按状态展示当前项目关联的任务。</p>
              </div>
            </div>
            {issues.error && <ErrorNotice error={issues.error} />}
            {agents.error && <ErrorNotice error={agents.error} />}
            {issues.isSuccess && projectIssues.length === 0 && <p className="muted">暂无关联任务。</p>}
            <IssueStatusBoard
              agents={agentList}
              issues={projectIssues}
              orgId={orgId}
              projects={project.data ? [project.data] : []}
              showProject={false}
            />
          </section>}
        </>
      )}
      </div>
    </OrgWorkspace>
  );
}
