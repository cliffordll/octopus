import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent, type PropsWithChildren } from "react";
import { Link, Navigate, NavLink, useParams } from "react-router-dom";
import { agentsApi } from "../api/agents";
import { organizationsApi } from "../api/organizations";
import { projectsApi } from "../api/projects";
import { Badge } from "../components/Badge";
import { ErrorNotice } from "../components/ErrorNotice";

export function OrganizationPage() {
  const { orgId = "" } = useParams();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const queryClient = useQueryClient();
  const organization = useQuery({
    queryKey: ["organization", orgId],
    queryFn: () => organizationsApi.get(orgId),
  });
  useEffect(() => {
    if (organization.data) {
      setName(organization.data.name);
      setDescription(organization.data.description ?? "");
    }
  }, [organization.data]);
  const update = useMutation({
    mutationFn: () =>
      organizationsApi.update(orgId, {
        name: name.trim(),
        description: description.trim() || null,
      }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["organization", orgId] }),
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    update.mutate();
  }
  if (organization.error) return <ErrorNotice error={organization.error} />;
  return (
    <div className="org-content organization-settings">
      <header className="page-header">
        <div>
          <p className="eyebrow">Organization Settings</p>
          <h1>组织设置</h1>
        </div>
      </header>
      <form className="panel form narrow" onSubmit={submit}>
        <label>
          组织名称
          <input value={name} onChange={(event) => setName(event.target.value)} required />
        </label>
        <label>
          描述
          <textarea value={description} onChange={(event) => setDescription(event.target.value)} />
        </label>
        {update.error && <ErrorNotice error={update.error} />}
        <button type="submit">保存组织</button>
      </form>
    </div>
  );
}

export function OrganizationIndexPage() {
  const { orgId = "" } = useParams();
  return <Navigate replace to={`/orgs/${orgId}/structure`} />;
}

export function OrganizationStructurePage() {
  const { orgId = "" } = useParams();
  const agents = useQuery({
    queryKey: ["agents", orgId],
    queryFn: () => agentsApi.list(orgId),
  });
  const agentList = Array.isArray(agents.data) ? agents.data : [];
  const agentNameById = new Map(agentList.map((agent) => [agent.id, agent.name]));

  return (
    <OrgWorkspace orgId={orgId}>
      <header className="page-header">
        <div><p className="eyebrow">Organization</p><h1>组织架构</h1></div>
      </header>
      {agents.error && <ErrorNotice error={agents.error} />}
      {agents.isSuccess && agentList.length === 0 ? (
        <section className="panel organization-empty-state">
          <p className="muted">暂无智能体。创建首个智能体以建立组织架构。</p>
          <Link className="button" to={`/orgs/${orgId}/agents/new`}>新建智能体</Link>
        </section>
      ) : (
        <section className="organization-structure">
          {agentList.map((agent) => (
            <article className="panel organization-member" key={agent.id}>
              <div className="organization-member-copy">
                <strong>{agent.name}</strong>
                <span>{agent.title ?? agent.role}</span>
              </div>
              <p>{agent.reportsTo ? `向 ${agentNameById.get(agent.reportsTo) ?? "未知智能体"} 汇报` : "直属组织"}</p>
              <Badge>{agent.status}</Badge>
            </article>
          ))}
        </section>
      )}
    </OrgWorkspace>
  );
}

export function OrgNavigation({ orgId }: { orgId: string }) {
  const projects = useQuery({
    queryKey: ["projects", orgId],
    queryFn: () => projectsApi.list(orgId),
  });
  const projectList = Array.isArray(projects.data) ? projects.data : [];
  return (
    <aside className="org-sidebar">
      <p className="org-sidebar-label">Organization</p>
      <nav className="local-nav" aria-label="组织导航">
        <section className="local-nav-section">
          <h2>组织</h2>
          <NavLink className="local-nav-primary" to={`/orgs/${orgId}/structure`}>组织架构</NavLink>
          <NavLink className="local-nav-primary" to={`/orgs/${orgId}/heartbeat-runs`}>心跳</NavLink>
        </section>
        <section className="local-nav-section">
          <h2>项目</h2>
          {projects.error && <ErrorNotice error={projects.error} />}
          <div className="local-project-list">
            {projectList.map((project) => (
              <NavLink
                className="local-nav-project local-nav-project-prominent"
                key={project.id}
                to={`/orgs/${orgId}/projects/${project.id}`}
              >
                {project.name}
              </NavLink>
            ))}
            {projects.isSuccess && projectList.length === 0 && <p className="context-empty">暂无项目</p>}
          </div>
        </section>
      </nav>
    </aside>
  );
}

export function OrgWorkspace({ orgId, children }: PropsWithChildren<{ orgId: string }>) {
  return (
    <div className="org-workspace">
      <OrgNavigation orgId={orgId} />
      <div className="org-content">{children}</div>
    </div>
  );
}
