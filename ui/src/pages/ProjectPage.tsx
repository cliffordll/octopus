import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { projectsApi } from "../api/projects";
import type { ProjectResourceRole, ProjectStatus } from "../api/types";
import { Badge } from "../components/Badge";
import { ErrorNotice } from "../components/ErrorNotice";
import { OrgNavigation } from "./OrganizationPage";

const STATUSES: ProjectStatus[] = ["backlog", "planned", "in_progress", "completed", "cancelled"];
const ROLES: ProjectResourceRole[] = [
  "working_set",
  "reference",
  "tracking",
  "deliverable",
  "background",
];

export function ProjectPage() {
  const { orgId = "", projectId = "" } = useParams();
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
    <>
      <header className="page-header">
        <div>
          <Link className="back-link" to={`/orgs/${orgId}/projects`}>返回 Projects</Link>
          <h1>{project.data?.name ?? "载入中..."}</h1>
        </div>
        <OrgNavigation orgId={orgId} />
      </header>
      {project.data && (
        <div className="grid-two detail-grid">
          <form className="panel form" onSubmit={save}>
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
          </form>
          <section className="panel">
            <h2>Resources</h2>
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
          </section>
        </div>
      )}
    </>
  );
}
