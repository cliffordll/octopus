import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { agentsApi } from "../api/agents";
import { goalsApi } from "../api/goals";
import type { GoalLevel, GoalStatus } from "../api/types";
import { ErrorNotice } from "../components/ErrorNotice";
import { GoalTree } from "../components/GoalTree";
import { TertiaryPageHeader } from "../components/TertiaryPageShell";
import { statusLabel } from "../utils/display";
import { OrgWorkspace } from "./OrganizationPage";

const LEVELS: GoalLevel[] = ["organization", "team", "agent", "task"];
const LEVEL_LABELS: Record<GoalLevel, string> = { organization: "组织", team: "团队", agent: "智能体", task: "任务" };
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
      <TertiaryPageHeader className="goals-page-header">
        <div>
          <p className="eyebrow">Goals</p>
          <h1>目标</h1>
          <p className="muted">维护组织、团队、智能体和任务层级的目标，并跟踪它们之间的父子关系。</p>
        </div>
        <button className="org-primary-action" type="button" onClick={() => setDialogOpen(true)}>创建目标</button>
      </TertiaryPageHeader>
      <section className="panel org-goal-list-card">
        <div className="org-section-header">
          <div>
            <p className="eyebrow">Goal Tree</p>
            <h2>目标列表</h2>
          </div>
        </div>
        {goals.error && <ErrorNotice error={goals.error} />}
        <div className="org-goal-list-body">
          <GoalTree goals={goalList} goalLink={(goal) => `/orgs/${orgId}/goals/${goal.id}`} />
        </div>
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
                <h2 id="create-goal-title">创建目标</h2>
                <p className="muted">设置目标的状态、层级、上级目标和负责人。</p>
              </div>
              <button aria-label="关闭" className="secondary" onClick={() => setDialogOpen(false)} type="button">关闭</button>
            </div>
            <form className="form task-create-form" onSubmit={submit}>
              <div className="task-form-row">
                <label className="form-field-full">目标名称<input autoFocus value={title} onChange={(event) => setTitle(event.target.value)} required /></label>
              </div>
              <div className="task-form-row">
                <label className="form-field-full">描述<textarea value={description} onChange={(event) => setDescription(event.target.value)} /></label>
              </div>
              <div className="task-form-row task-form-grid">
                <label>
                  层级
                  <select value={level} onChange={(event) => setLevel(event.target.value as GoalLevel)}>
                    {LEVELS.map((item) => <option key={item} value={item}>{LEVEL_LABELS[item]}</option>)}
                  </select>
                </label>
                <label>
                  状态
                  <select value={status} onChange={(event) => setStatus(event.target.value as GoalStatus)}>
                    {STATUSES.map((item) => <option key={item} value={item}>{statusLabel(item)}</option>)}
                  </select>
                </label>
              </div>
              <div className="task-form-row task-form-grid">
                <label>
                  上级目标
                  <select value={parentId} onChange={(event) => setParentId(event.target.value)}>
                    <option value="">无</option>
                    {goalList.map((goal) => <option key={goal.id} value={goal.id}>{goal.title}</option>)}
                  </select>
                </label>
                <label>
                  负责人
                  <select value={ownerAgentId} onChange={(event) => setOwnerAgentId(event.target.value)}>
                    <option value="">未设置</option>
                    {agentList.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}
                  </select>
                </label>
              </div>
              {agents.error && <ErrorNotice error={agents.error} />}
              {create.error && <ErrorNotice error={create.error} />}
              <div className="task-modal-actions">
                <button className="secondary" onClick={() => setDialogOpen(false)} type="button">取消</button>
                <button disabled={create.isPending} type="submit">创建</button>
              </div>
            </form>
          </section>
        </div>
      )}
    </OrgWorkspace>
  );
}
