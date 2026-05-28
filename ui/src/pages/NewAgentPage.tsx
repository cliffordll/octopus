import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { agentsApi } from "../api/agents";
import type { AgentRole, AgentRuntimeType } from "../api/types";
import { AgentsWorkspace } from "../components/ContextWorkspace";
import { ErrorNotice } from "../components/ErrorNotice";

const ROLES: AgentRole[] = ["ceo", "engineer", "qa", "pm", "designer", "devops", "researcher", "general"];
const RUNTIMES: AgentRuntimeType[] = ["process", "http", "codex_local", "claude_local", "opencode_local"];

function parseCsv(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function NewAgentPage() {
  const { orgId = "" } = useParams();
  const [name, setName] = useState("");
  const [role, setRole] = useState<AgentRole>("engineer");
  const [runtime, setRuntime] = useState<AgentRuntimeType>("process");
  const [desiredSkills, setDesiredSkills] = useState("");
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const agents = useQuery({ queryKey: ["agents", orgId], queryFn: () => agentsApi.list(orgId) });
  const isFirstAgent = agents.isSuccess && agents.data.length === 0;
  const effectiveRole: AgentRole = isFirstAgent ? "ceo" : role;
  const create = useMutation({
    mutationFn: () =>
      agentsApi.create(orgId, {
        name: name.trim(),
        role: effectiveRole,
        agentRuntimeType: runtime,
        agentRuntimeConfig: {},
        ...(desiredSkills.trim() ? { desiredSkills: parseCsv(desiredSkills) } : {}),
      }),
    onSuccess: (agent) => {
      void queryClient.invalidateQueries({ queryKey: ["agents", orgId] });
      navigate(`/orgs/${orgId}/agents/${agent.id}/configuration`);
    },
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    if (name.trim()) create.mutate();
  }
  return (
    <AgentsWorkspace orgId={orgId}>
      <header className="page-header">
        <div>
          <Link className="back-link" to={`/orgs/${orgId}/agents`}>返回智能体列表</Link>
          <h1>{isFirstAgent ? "创建 CEO" : "新建智能体"}</h1>
        </div>
      </header>
      <form className="panel form agent-create-form" onSubmit={submit}>
        {isFirstAgent && <p className="muted">首个智能体将作为 CEO 创建</p>}
        <label>智能体名称<input value={name} onChange={(event) => setName(event.target.value)} required /></label>
        <label>
          角色
          <select disabled={isFirstAgent} value={effectiveRole} onChange={(event) => setRole(event.target.value as AgentRole)}>
            {ROLES.map((item) => <option key={item}>{item}</option>)}
          </select>
        </label>
        <label>
          Runtime
          <select value={runtime} onChange={(event) => setRuntime(event.target.value as AgentRuntimeType)}>
            {RUNTIMES.map((item) => <option key={item}>{item}</option>)}
          </select>
        </label>
        <label>
          Desired Skills
          <input value={desiredSkills} onChange={(event) => setDesiredSkills(event.target.value)} />
        </label>
        {create.error && <ErrorNotice error={create.error} />}
        <button disabled={!agents.isSuccess || create.isPending} type="submit">
          {isFirstAgent ? "创建 CEO" : "新建智能体"}
        </button>
      </form>
    </AgentsWorkspace>
  );
}
