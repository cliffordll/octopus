import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Navigate, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { projectsApi } from "../api/projects";
import type { ProjectStatus } from "../api/types";
import { ErrorNotice } from "../components/ErrorNotice";
import { statusLabel } from "../utils/display";
import { OrgWorkspace } from "./OrganizationPage";

const STATUSES: ProjectStatus[] = ["backlog", "planned", "in_progress", "completed", "cancelled"];

export function ProjectCreateDialog({ onClose, orgId }: { onClose: () => void; orgId: string }) {
  const [name, setName] = useState("");
  const [status, setStatus] = useState<ProjectStatus>("backlog");
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const create = useMutation({
    mutationFn: () => projectsApi.create(orgId, { name: name.trim(), status }),
    onSuccess: (project) => {
      setName("");
      setStatus("backlog");
      onClose();
      void queryClient.invalidateQueries({ queryKey: ["projects", orgId] });
      navigate(`/orgs/${orgId}/projects/${project.id}`);
    },
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    if (name.trim()) create.mutate();
  }
  return (
    <div aria-label="创建项目" aria-modal="true" className="modal-backdrop" role="dialog">
      <form className="panel form task-modal task-create-modal project-create-dialog" onSubmit={submit}>
        <div className="task-modal-header">
          <div>
            <p className="eyebrow">Project</p>
            <h2>创建项目</h2>
          </div>
          <button className="secondary small-button" onClick={onClose} type="button">关闭</button>
        </div>
        <label>
          项目名称
          <input value={name} onChange={(event) => setName(event.target.value)} required />
        </label>
        <label>
          项目状态
          <select value={status} onChange={(event) => setStatus(event.target.value as ProjectStatus)}>
            {STATUSES.map((item) => <option key={item} value={item}>{statusLabel(item)}</option>)}
          </select>
        </label>
        {create.error && <ErrorNotice error={create.error} />}
        <div className="task-modal-actions">
          <button className="secondary" onClick={onClose} type="button">取消</button>
          <button disabled={create.isPending} type="submit">创建项目</button>
        </div>
      </form>
    </div>
  );
}

export function ProjectsPage() {
  const { orgId = "" } = useParams();
  const [searchParams] = useSearchParams();
  const shouldOpenCreate = searchParams.get("create") === "1";
  const [dialogOpen, setDialogOpen] = useState(false);
  const navigate = useNavigate();
  const projects = useQuery({
    queryKey: ["projects", orgId],
    queryFn: () => projectsApi.list(orgId),
  });
  function closeDialog() {
    setDialogOpen(false);
    if (shouldOpenCreate) navigate(`/orgs/${orgId}/projects`);
  }
  return (
    <OrgWorkspace contentClassName="org-content-full" orgId={orgId}>
      {projects.isSuccess && projects.data.length > 0 && !shouldOpenCreate && (
        <Navigate replace to={`/orgs/${orgId}/projects/${projects.data[0]!.id}`} />
      )}
      <header className="page-header">
        <div>
          <p className="eyebrow">Projects</p>
          <h1>项目</h1>
          <p className="muted">当前组织下的项目。</p>
        </div>
      </header>
      {projects.error && <ErrorNotice error={projects.error} />}
      {projects.isSuccess && projects.data.length === 0 && (
        <section className="panel project-empty-state">
          <h2>暂无项目</h2>
          <p className="muted">创建项目后可管理配置、资源和任务。</p>
          <button type="button" onClick={() => setDialogOpen(true)}>创建项目</button>
        </section>
      )}
      {(dialogOpen || shouldOpenCreate) && <ProjectCreateDialog onClose={closeDialog} orgId={orgId} />}
    </OrgWorkspace>
  );
}
