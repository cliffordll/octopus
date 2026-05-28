import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, NavLink, useNavigate, useParams } from "react-router-dom";
import { agentsApi } from "../api/agents";
import { goalsApi } from "../api/goals";
import { issuesApi } from "../api/issues";
import { projectsApi } from "../api/projects";
import type { Goal, GoalLevel, GoalStatus, IssueListItem, ProjectDetail } from "../api/types";
import { Badge } from "../components/Badge";
import { ErrorNotice } from "../components/ErrorNotice";
import { GoalTree } from "../components/GoalTree";
import { OrgWorkspace } from "./OrganizationPage";

const LEVELS: GoalLevel[] = ["organization", "team", "agent", "task"];
const STATUSES: GoalStatus[] = ["planned", "active", "achieved", "cancelled"];

function SummaryMetric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="summary-metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function linkedToGoal(project: ProjectDetail, goalId: string): boolean {
  if (project.goalId === goalId) return true;
  if (project.goalIds?.includes(goalId)) return true;
  return project.goals?.some((goal) => goal.id === goalId) ?? false;
}

function WorkSection({
  orgId,
  linkedProjects,
  linkedIssues,
}: {
  orgId: string;
  linkedProjects: ProjectDetail[];
  linkedIssues: IssueListItem[];
}) {
  if (linkedProjects.length === 0 && linkedIssues.length === 0) {
    return <section className="panel"><p className="muted">No linked work yet.</p></section>;
  }
  return (
    <div className="goal-work-sections">
      <section className="panel">
        <h2>Projects ({linkedProjects.length})</h2>
        <div className="list">
          {linkedProjects.map((project) => (
            <article className="row" key={project.id}>
              <Link to={`/orgs/${orgId}/projects/${project.id}`}>{project.name}</Link>
              <Badge>{project.status}</Badge>
            </article>
          ))}
          {linkedProjects.length === 0 && <p className="muted">No linked projects.</p>}
        </div>
      </section>
      <section className="panel">
        <h2>Issues ({linkedIssues.length})</h2>
        <div className="list">
          {linkedIssues.map((issue) => (
            <article className="issue-row" key={issue.id}>
              <span className="identifier">{issue.identifier ?? "-"}</span>
              <Link to={`/orgs/${orgId}/issues/${issue.id}`}>{issue.title}</Link>
              <Badge>{issue.status}</Badge>
            </article>
          ))}
          {linkedIssues.length === 0 && <p className="muted">No linked issues.</p>}
        </div>
      </section>
    </div>
  );
}

export function GoalPage() {
  const { orgId = "", goalId = "", tab = "work" } = useParams();
  const activeTab = ["work", "children", "activity", "configuration"].includes(tab) ? tab : "work";
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [level, setLevel] = useState<GoalLevel>("task");
  const [status, setStatus] = useState<GoalStatus>("planned");
  const [parentId, setParentId] = useState("");
  const [ownerAgentId, setOwnerAgentId] = useState("");
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const goal = useQuery({ queryKey: ["goal", goalId], queryFn: () => goalsApi.get(goalId) });
  const goals = useQuery({ queryKey: ["goals", orgId], queryFn: () => goalsApi.list(orgId) });
  const agents = useQuery({ queryKey: ["agents", orgId], queryFn: () => agentsApi.list(orgId) });
  const projects = useQuery({ queryKey: ["projects", orgId], queryFn: () => projectsApi.list(orgId) });
  const issues = useQuery({ queryKey: ["issues", orgId, "goal", goalId], queryFn: () => issuesApi.list(orgId, { goalId }) });
  const dependencies = useQuery({ queryKey: ["goal-dependencies", goalId], queryFn: () => goalsApi.dependencies(goalId) });
  const goalList = Array.isArray(goals.data) ? goals.data : [];
  const agentList = Array.isArray(agents.data) ? agents.data : [];
  const childGoals = goalList.filter((item) => item.parentId === goalId);
  const linkedProjects = useMemo(
    () => (projects.data ?? []).filter((project) => linkedToGoal(project, goalId)),
    [projects.data, goalId],
  );
  const linkedIssues = issues.data ?? [];
  const ownerAgent = goal.data?.ownerAgentId ? agentList.find((agent) => agent.id === goal.data?.ownerAgentId) : null;
  const parentGoal = goal.data?.parentId ? goalList.find((item) => item.id === goal.data?.parentId) : null;

  useEffect(() => {
    if (!goal.data) return;
    setTitle(goal.data.title);
    setDescription(goal.data.description ?? "");
    setLevel(goal.data.level);
    setStatus(goal.data.status);
    setParentId(goal.data.parentId ?? "");
    setOwnerAgentId(goal.data.ownerAgentId ?? "");
  }, [goal.data]);

  const update = useMutation({
    mutationFn: (payload: Partial<Goal>) => goalsApi.update(goalId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["goal", goalId] });
      void queryClient.invalidateQueries({ queryKey: ["goals", orgId] });
      void queryClient.invalidateQueries({ queryKey: ["goal-dependencies", goalId] });
    },
  });
  const remove = useMutation({
    mutationFn: () => goalsApi.remove(goalId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["goals", orgId] });
      navigate(`/orgs/${orgId}/goals`);
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!title.trim()) return;
    update.mutate({
      title: title.trim(),
      description: description.trim() || null,
      level,
      status,
      parentId: parentId || null,
      ownerAgentId: ownerAgentId || null,
    });
  }

  if (goal.error) return <ErrorNotice error={goal.error} />;

  return (
    <OrgWorkspace orgId={orgId}>
      <header className="page-header">
        <div>
          <Link className="back-link" to={`/orgs/${orgId}/goals`}>返回 Goals</Link>
          <div className="agent-title-row">
            <h1>{goal.data?.title ?? "Goal"}</h1>
            {goal.data && <Badge>{goal.data.status}</Badge>}
          </div>
        </div>
        {goal.data && (
          <div className="agent-header-actions">
            <button className="secondary" disabled={update.isPending} onClick={() => update.mutate({ status: "cancelled" })} type="button">Cancel goal</button>
            <button className="danger" disabled={remove.isPending || (dependencies.data?.blockers.length ?? 0) > 0} onClick={() => remove.mutate()} type="button">Delete</button>
          </div>
        )}
      </header>
      {goal.data && (
        <>
          <div className="goal-summary-grid">
            <SummaryMetric label="Owner" value={ownerAgent?.name ?? "None"} />
            <SummaryMetric label="Parent" value={parentGoal?.title ?? "None"} />
            <SummaryMetric label="Sub-goals" value={childGoals.length} />
            <SummaryMetric label="Projects" value={linkedProjects.length} />
            <SummaryMetric label="Issues" value={linkedIssues.length} />
            <SummaryMetric label="Updated" value={goal.data.updatedAt || "-"} />
          </div>
          <nav aria-label="目标详情导航" className="detail-tabs">
            <NavLink to={`/orgs/${orgId}/goals/${goalId}/work`}>Work ({linkedProjects.length + linkedIssues.length})</NavLink>
            <NavLink to={`/orgs/${orgId}/goals/${goalId}/children`}>Sub-Goals ({childGoals.length})</NavLink>
            <NavLink to={`/orgs/${orgId}/goals/${goalId}/activity`}>Activity</NavLink>
            <NavLink to={`/orgs/${orgId}/goals/${goalId}/configuration`}>Configuration</NavLink>
          </nav>
          {activeTab === "work" && <WorkSection linkedIssues={linkedIssues} linkedProjects={linkedProjects} orgId={orgId} />}
          {activeTab === "children" && (
            <section className="panel">
              <h2>Sub-Goals</h2>
              <GoalTree goals={childGoals} goalLink={(goal) => `/orgs/${orgId}/goals/${goal.id}`} />
            </section>
          )}
          {activeTab === "activity" && (
            <section className="panel">
              <h2>Activity</h2>
              <p className="muted">Activity API 尚未接入 UI，当前仅展示目标依赖状态。</p>
              <p className="muted">Blockers: {dependencies.data?.blockers.length ? dependencies.data.blockers.join(", ") : "None"}</p>
            </section>
          )}
          {activeTab === "configuration" && (
            <form className="panel form" onSubmit={submit}>
              <h2>Configuration</h2>
              <label>Goal title<input value={title} onChange={(event) => setTitle(event.target.value)} required /></label>
              <label>Description<textarea value={description} onChange={(event) => setDescription(event.target.value)} /></label>
              <div className="task-form-grid">
                <label>
                  Level
                  <select value={level} onChange={(event) => setLevel(event.target.value as GoalLevel)}>
                    {LEVELS.map((item) => <option key={item}>{item}</option>)}
                  </select>
                </label>
                <label>
                  Status
                  <select value={status} onChange={(event) => setStatus(event.target.value as GoalStatus)}>
                    {STATUSES.map((item) => <option key={item}>{item}</option>)}
                  </select>
                </label>
              </div>
              <label>
                Parent goal
                <select value={parentId} onChange={(event) => setParentId(event.target.value)}>
                  <option value="">None</option>
                  {goalList.filter((item) => item.id !== goalId).map((item) => (
                    <option key={item.id} value={item.id}>{item.title}</option>
                  ))}
                </select>
              </label>
              <label>
                Owner
                <select value={ownerAgentId} onChange={(event) => setOwnerAgentId(event.target.value)}>
                  <option value="">None</option>
                  {agentList.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}
                </select>
              </label>
              {agents.error && <ErrorNotice error={agents.error} />}
              {update.error && <ErrorNotice error={update.error} />}
              {remove.error && <ErrorNotice error={remove.error} />}
              <button disabled={update.isPending} type="submit">Save goal</button>
            </form>
          )}
        </>
      )}
    </OrgWorkspace>
  );
}
