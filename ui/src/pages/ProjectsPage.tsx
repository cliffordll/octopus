import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { projectsApi } from "../api/projects";
import type { ProjectStatus } from "../api/types";
import { Badge } from "../components/Badge";
import { ErrorNotice } from "../components/ErrorNotice";
import { OrgNavigation } from "./OrganizationPage";

const STATUSES: ProjectStatus[] = ["backlog", "planned", "in_progress", "completed", "cancelled"];

export function ProjectsPage() {
  const { orgId = "" } = useParams();
  const [name, setName] = useState("");
  const [status, setStatus] = useState<ProjectStatus>("backlog");
  const queryClient = useQueryClient();
  const projects = useQuery({
    queryKey: ["projects", orgId],
    queryFn: () => projectsApi.list(orgId),
  });
  const create = useMutation({
    mutationFn: () => projectsApi.create(orgId, { name: name.trim(), status }),
    onSuccess: () => {
      setName("");
      setStatus("backlog");
      void queryClient.invalidateQueries({ queryKey: ["projects", orgId] });
    },
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    if (name.trim()) create.mutate();
  }
  return (
    <>
      <header className="page-header">
        <div><p className="eyebrow">Projects</p><h1>项目</h1></div>
        <OrgNavigation orgId={orgId} />
      </header>
      <div className="grid-two">
        <section className="panel">
          <h2>现有 Project</h2>
          {projects.error && <ErrorNotice error={projects.error} />}
          <div className="list">
            {projects.data?.map((project) => (
              <article className="row" key={project.id}>
                <Link to={`/orgs/${orgId}/projects/${project.id}`}>{project.name}</Link>
                <Badge>{project.status}</Badge>
              </article>
            ))}
          </div>
        </section>
        <form className="panel form" onSubmit={submit}>
          <h2>创建 Project</h2>
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
          <button type="submit">新建 Project</button>
        </form>
      </div>
    </>
  );
}
