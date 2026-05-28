import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { Link, NavLink, useParams } from "react-router-dom";
import { issuesApi } from "../api/issues";
import { projectsApi } from "../api/projects";
import type { ProjectResourceRole, ProjectStatus } from "../api/types";
import { Badge } from "../components/Badge";
import { ErrorNotice } from "../components/ErrorNotice";
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
  useEffect(() => {
    if (project.data) {
      setDescription(project.data.description ?? "");
      setStatus(project.data.status);
    }
  }, [project.data]);
  const update = useMutation({
    mutationFn: () => projectsApi.update(projectId, { description: description.trim() || null, status }),
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
  if (project.error) return <ErrorNotice error={project.error} />;
  return (
    <OrgWorkspace orgId={orgId}>
      <header className="page-header">
        <div>
          <Link className="back-link" to={`/orgs/${orgId}/projects`}>返回 Projects</Link>
          <h1>{project.data?.name ?? "载入中..."}</h1>
        </div>
      </header>
      {project.data && (
        <>
          <nav aria-label="项目详情导航" className="detail-tabs">
            <NavLink to={`/orgs/${orgId}/projects/${projectId}/configuration`}>配置</NavLink>
            <NavLink to={`/orgs/${orgId}/projects/${projectId}/resources`}>资源</NavLink>
            <NavLink to={`/orgs/${orgId}/projects/${projectId}/issues`}>任务</NavLink>
          </nav>
          {activeTab === "configuration" && <form className="panel form project-configuration" onSubmit={save}>
            <div className="meta-line"><Badge>{project.data.urlKey}</Badge><Badge>{project.data.status}</Badge></div>
            <label>
              描述
              <textarea value={description} onChange={(event) => setDescription(event.target.value)} />
            </label>
            <label>
              状态
              <select value={status} onChange={(event) => setStatus(event.target.value as ProjectStatus)}>
                {STATUSES.map((item) => <option key={item}>{item}</option>)}
              </select>
            </label>
            {update.error && <ErrorNotice error={update.error} />}
            <button type="submit">保存 Project</button>
          </form>}
          {activeTab === "resources" && <section className="panel project-resources">
            <h2>资源</h2>
            {resources.error && <ErrorNotice error={resources.error} />}
            <div className="list">
              {resources.data?.map((attachment) => (
                <article className="row" key={attachment.id}>
                  <span>{attachment.resource.name}</span>
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
          {activeTab === "issues" && <section className="panel project-issues">
            <h2>任务</h2>
            {issues.error && <ErrorNotice error={issues.error} />}
            {issues.isSuccess && issues.data.length === 0 && <p className="muted">暂无关联任务。</p>}
            <div className="list">
              {issues.data?.map((issue) => (
                <article className="issue-row" key={issue.id}>
                  <span className="identifier">{issue.identifier ?? "-"}</span>
                  <Link to={`/orgs/${orgId}/issues/${issue.id}`}>{issue.title}</Link>
                  <Badge>{issue.priority}</Badge>
                  <Badge>{issue.status}</Badge>
                </article>
              ))}
            </div>
          </section>}
        </>
      )}
    </OrgWorkspace>
  );
}
