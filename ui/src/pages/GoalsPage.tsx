import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { agentsApi } from "../api/agents";
import { goalsApi } from "../api/goals";
import type { GoalLevel, GoalStatus } from "../api/types";
import { ErrorNotice } from "../components/ErrorNotice";
import { GoalTree } from "../components/GoalTree";
import { OrgWorkspace } from "./OrganizationPage";

const LEVELS: GoalLevel[] = ["organization", "team", "agent", "task"];
const STATUSES: GoalStatus[] = ["planned", "active", "achieved", "cancelled"];

export function GoalsPage() {
  const { orgId = "" } = useParams();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [level, setLevel] = useState<GoalLevel>("task");
  const [status, setStatus] = useState<GoalStatus>("planned");
  const [parentId, setParentId] = useState("");
  const [ownerAgentId, setOwnerAgentId] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const goals = useQuery({ queryKey: ["goals", orgId], queryFn: () => goalsApi.list(orgId) });
  const agents = useQuery({ queryKey: ["agents", orgId], queryFn: () => agentsApi.list(orgId) });
  const goalList = Array.isArray(goals.data) ? goals.data : [];
  const agentList = Array.isArray(agents.data) ? agents.data : [];
  const create = useMutation({
    mutationFn: () =>
      goalsApi.create(orgId, {
        title: title.trim(),
        ...(description.trim() ? { description: description.trim() } : {}),
        level,
        status,
        ...(parentId ? { parentId } : {}),
        ...(ownerAgentId ? { ownerAgentId } : {}),
      }),
    onSuccess: (goal) => {
      setTitle("");
      setDescription("");
      setLevel("task");
      setStatus("planned");
      setParentId("");
      setOwnerAgentId("");
      setDialogOpen(false);
      void queryClient.invalidateQueries({ queryKey: ["goals", orgId] });
      navigate(`/orgs/${orgId}/goals/${goal.id}`);
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    if (title.trim()) create.mutate();
  }

  return (
    <OrgWorkspace contentClassName="org-content-full" orgId={orgId}>
      <header className="page-header">
        <div><p className="eyebrow">Goals</p><h1>目标</h1></div>
        <button type="button" onClick={() => setDialogOpen(true)}>New Goal</button>
      </header>
      <section className="panel">
        <h2>Goals</h2>
        {goals.error && <ErrorNotice error={goals.error} />}
        <GoalTree goals={goalList} goalLink={(goal) => `/orgs/${orgId}/goals/${goal.id}`} />
      </section>
      {dialogOpen && (
        <div
          className="modal-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setDialogOpen(false);
          }}
          role="presentation"
        >
          <section aria-labelledby="create-goal-title" aria-modal="true" className="panel task-modal task-create-modal" role="dialog">
            <div className="task-modal-header">
              <div>
                <h2 id="create-goal-title">New Goal</h2>
                <p className="muted">Create a goal with status, level, parent, and owner.</p>
              </div>
              <button aria-label="关闭" className="secondary" onClick={() => setDialogOpen(false)} type="button">关闭</button>
            </div>
            <form className="form task-create-form" onSubmit={submit}>
              <div className="task-form-row">
                <label className="form-field-full">Goal title<input autoFocus value={title} onChange={(event) => setTitle(event.target.value)} required /></label>
              </div>
              <div className="task-form-row">
                <label className="form-field-full">Description<textarea value={description} onChange={(event) => setDescription(event.target.value)} /></label>
              </div>
              <div className="task-form-row task-form-grid">
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
              <div className="task-form-row task-form-grid">
                <label>
                  Parent goal
                  <select value={parentId} onChange={(event) => setParentId(event.target.value)}>
                    <option value="">无</option>
                    {goalList.map((goal) => <option key={goal.id} value={goal.id}>{goal.title}</option>)}
                  </select>
                </label>
                <label>
                  Owner
                  <select value={ownerAgentId} onChange={(event) => setOwnerAgentId(event.target.value)}>
                    <option value="">未设置</option>
                    {agentList.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}
                  </select>
                </label>
              </div>
              {agents.error && <ErrorNotice error={agents.error} />}
              {create.error && <ErrorNotice error={create.error} />}
              <div className="task-modal-actions">
                <button className="secondary" onClick={() => setDialogOpen(false)} type="button">Cancel</button>
                <button disabled={create.isPending} type="submit">Create goal</button>
              </div>
            </form>
          </section>
        </div>
      )}
    </OrgWorkspace>
  );
}
