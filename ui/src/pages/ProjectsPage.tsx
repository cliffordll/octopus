import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import { projectsApi } from "../api/projects";
import type { ProjectStatus } from "../api/types";
import { ErrorNotice } from "../components/ErrorNotice";
import { OrgWorkspace } from "./OrganizationPage";

const STATUSES: ProjectStatus[] = ["backlog", "planned", "in_progress", "completed", "cancelled"];

export function ProjectsPage() {
  const { orgId = "" } = useParams();
  const [name, setName] = useState("");
  const [status, setStatus] = useState<ProjectStatus>("backlog");
  const [dialogOpen, setDialogOpen] = useState(false);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const projects = useQuery({
    queryKey: ["projects", orgId],
    queryFn: () => projectsApi.list(orgId),
  });
  const create = useMutation({
    mutationFn: () => projectsApi.create(orgId, { name: name.trim(), status }),
    onSuccess: (project) => {
      setName("");
      setStatus("backlog");
      setDialogOpen(false);
      void queryClient.invalidateQueries({ queryKey: ["projects", orgId] });
      navigate(`/orgs/${orgId}/projects/${project.id}`);
    },
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    if (name.trim()) create.mutate();
  }
  return (
    <OrgWorkspace orgId={orgId}>
      {projects.isSuccess && projects.data.length > 0 && (
        <Navigate replace to={`/orgs/${orgId}/projects/${projects.data[0]!.id}`} />
      )}
      <header className="page-header">
        <div>
          <p className="eyebrow">Projects</p>
          <h1>项目</h1>
          <p className="muted">参考上游项目入口，项目作为组织下的工作空间入口。</p>
        </div>
      </header>
      {projects.error && <ErrorNotice error={projects.error} />}
      {projects.isSuccess && projects.data.length === 0 && (
        <section className="panel project-empty-state">
          <h2>No projects yet.</h2>
          <p className="muted">创建项目后，可以在详情页管理配置、资源和任务。</p>
          <button type="button" onClick={() => setDialogOpen(true)}>Add Project</button>
        </section>
      )}
      {dialogOpen && (
        <div aria-label="Add Project" aria-modal="true" className="task-modal-backdrop" role="dialog">
          <form className="task-modal task-create-modal project-create-dialog" onSubmit={submit}>
            <div className="task-modal-header">
              <div>
                <p className="eyebrow">Project</p>
                <h2>Add Project</h2>
              </div>
              <button className="secondary small-button" onClick={() => setDialogOpen(false)} type="button">关闭</button>
            </div>
            <label>
              Project 名称
              <input value={name} onChange={(event) => setName(event.target.value)} required />
            </label>
            <label>
              Project 状态
              <select value={status} onChange={(event) => setStatus(event.target.value as ProjectStatus)}>
                {STATUSES.map((item) => <option key={item}>{item}</option>)}
              </select>
            </label>
            {create.error && <ErrorNotice error={create.error} />}
            <div className="task-modal-actions">
              <button className="secondary" onClick={() => setDialogOpen(false)} type="button">Cancel</button>
              <button disabled={create.isPending} type="submit">新建 Project</button>
            </div>
          </form>
        </div>
      )}
    </OrgWorkspace>
  );
}
