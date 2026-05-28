import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { Link, NavLink, useParams } from "react-router-dom";
import { agentsApi } from "../api/agents";
import { issuesApi } from "../api/issues";
import { projectsApi } from "../api/projects";
import type { ProjectResourceRole, ProjectStatus } from "../api/types";
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

export function ProjectPage() {
  const { orgId = "", projectId = "", tab = "configuration" } = useParams();
  const activeTab = ["configuration", "resources", "issues"].includes(tab) ? tab : "configuration";
  const [projectName, setProjectName] = useState("");
  const [description, setDescription] = useState("");
  const [status, setStatus] = useState<ProjectStatus>("backlog");
  const [resourceId, setResourceId] = useState("");
  const [role, setRole] = useState<ProjectResourceRole>("working_set");
  const queryClient = useQueryClient();
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
    enabled: activeTab === "issues",
  });
  useEffect(() => {
    if (project.data) {
      setProjectName(project.data.name);
      setDescription(project.data.description ?? "");
      setStatus(project.data.status);
    }
  }, [project.data]);
  const update = useMutation({
    mutationFn: () => projectsApi.update(projectId, {
      description: description.trim() || null,
      name: projectName.trim() || project.data?.name,
      status,
    }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["project", projectId] }),
  });
  const addResource = useMutation({
    mutationFn: () => projectsApi.addResource(projectId, { resourceId: resourceId.trim(), role }),
    onSuccess: () => {
      setResourceId("");
      void queryClient.invalidateQueries({ queryKey: ["project-resources", projectId] });
    },
  });
  const removeResource = useMutation({
    mutationFn: (attachmentId: string) => projectsApi.removeResource(projectId, attachmentId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["project-resources", projectId] }),
  });
  function save(event: FormEvent) {
    event.preventDefault();
    update.mutate();
  }
  function attach(event: FormEvent) {
    event.preventDefault();
    if (resourceId.trim()) addResource.mutate();
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
            <Link className="back-link" to={`/orgs/${orgId}/projects`}>返回 Projects</Link>
            <div className="project-heading-row">
              <h1>{project.data?.name ?? "载入中..."}</h1>
            </div>
            {project.data && (
              <div className="project-header-meta">
                <Badge>{project.data.status}</Badge>
                <Badge>{project.data.urlKey}</Badge>
                <span>{project.data.leadAgentId ?? "No lead"}</span>
              </div>
            )}
            {project.data?.description && <p className="muted">{project.data.description}</p>}
          </div>
        </div>
        {project.data && <Link className="button secondary" to={`/orgs/${orgId}/chats`}>Chat</Link>}
      </header>
      {project.data && (
        <>
          {project.data.pauseReason === "budget" && (
            <div className="project-budget-stop">
              <span />
              Paused by budget hard stop
            </div>
          )}
          <div className="project-summary-grid">
            <div className="summary-metric"><span>Status</span><strong>{project.data.status}</strong></div>
            <div className="summary-metric"><span>Lead</span><strong>{project.data.leadAgentId ?? "None"}</strong></div>
            <div className="summary-metric"><span>Target</span><strong>{project.data.targetDate ?? "None"}</strong></div>
            <div className="summary-metric"><span>Updated</span><strong>{project.data.updatedAt || "-"}</strong></div>
          </div>
          <nav aria-label="项目详情导航" className="detail-tabs">
            <NavLink to={`/orgs/${orgId}/projects/${projectId}/configuration`}>Configuration</NavLink>
            <NavLink to={`/orgs/${orgId}/projects/${projectId}/resources`}>Resources</NavLink>
            <NavLink to={`/orgs/${orgId}/projects/${projectId}/issues`}>Issues</NavLink>
          </nav>
          {activeTab === "configuration" && <form className="panel project-properties-card project-tab-panel" onSubmit={save}>
            <div className="panel-heading">
              <div>
                <h2>Configuration</h2>
                <p className="muted">项目属性以行内配置方式展示，布局对齐上游 ProjectProperties。</p>
              </div>
            </div>
            <div className="project-property-list">
              <label className="project-property-row">
                <span>Name</span>
                <input value={projectName} onChange={(event) => setProjectName(event.target.value)} required />
              </label>
              <label className="project-property-row project-property-row-start">
                <span>描述</span>
                <textarea value={description} onChange={(event) => setDescription(event.target.value)} />
              </label>
              <label className="project-property-row">
                <span>Status</span>
                <select value={status} onChange={(event) => setStatus(event.target.value as ProjectStatus)}>
                  {STATUSES.map((item) => <option key={item}>{item}</option>)}
                </select>
              </label>
              <div className="project-property-row">
                <span>URL Key</span>
                <strong>{project.data.urlKey}</strong>
              </div>
              <div className="project-property-row">
                <span>Lead</span>
                <strong>{project.data.leadAgentId ?? "None"}</strong>
              </div>
              <div className="project-property-row">
                <span>Goals</span>
                <div className="project-goal-chips">
                  {(project.data.goals ?? []).map((goal) => <Badge key={goal.id}>{goal.title}</Badge>)}
                  {(project.data.goals ?? []).length === 0 && project.data.goalId && <Badge>{project.data.goalId}</Badge>}
                  {(project.data.goals ?? []).length === 0 && !project.data.goalId && <span className="muted">No linked goals</span>}
                </div>
              </div>
              <div className="project-property-row">
                <span>Created</span>
                <strong>{project.data.createdAt || "-"}</strong>
              </div>
              <div className="project-property-row">
                <span>Updated</span>
                <strong>{project.data.updatedAt || "-"}</strong>
              </div>
            </div>
            {update.error && <ErrorNotice error={update.error} />}
            <div className="project-property-actions">
              <button type="submit">保存 Project</button>
            </div>
          </form>}
          {activeTab === "resources" && <section className="panel project-resources project-tab-panel-wide">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">Project Context</p>
                <h2>Resources</h2>
                <p className="muted">选择智能体在本项目真正需要使用的资源，组织资源目录保持统一管理。</p>
              </div>
            </div>
            {resources.error && <ErrorNotice error={resources.error} />}
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
                    onClick={() => removeResource.mutate(attachment.id)}
                    type="button"
                  >
                    移除
                  </button>
                </article>
              ))}
              {resources.isSuccess && resources.data.length === 0 && <p className="muted">No resources attached.</p>}
            </div>
            <form className="form resource-form" onSubmit={attach}>
              <label>
                Resource ID
                <input value={resourceId} onChange={(event) => setResourceId(event.target.value)} required />
              </label>
              <label>
                Role
                <select value={role} onChange={(event) => setRole(event.target.value as ProjectResourceRole)}>
                  {ROLES.map((item) => <option key={item}>{item}</option>)}
                </select>
              </label>
              {addResource.error && <ErrorNotice error={addResource.error} />}
              <button type="submit">添加 Resource</button>
            </form>
          </section>}
          {activeTab === "issues" && <section className="panel project-issues project-tab-panel-wide">
            <div className="panel-heading">
              <div>
                <h2>Issues</h2>
                <p className="muted">当前项目关联任务，按状态分组展示。</p>
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
