import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { agentsApi } from "../api/agents";
import type { AgentRole, AgentRuntimeType } from "../api/types";
import { Badge } from "../components/Badge";
import { ErrorNotice } from "../components/ErrorNotice";
import { OrgNavigation } from "./OrganizationPage";

const ROLES: AgentRole[] = ["ceo", "engineer", "qa", "pm", "designer", "devops", "researcher", "general"];
const RUNTIMES: AgentRuntimeType[] = ["process", "codex_local"];

export function AgentsPage() {
  const { orgId = "" } = useParams();
  const [name, setName] = useState("");
  const [role, setRole] = useState<AgentRole>("engineer");
  const [runtime, setRuntime] = useState<AgentRuntimeType>("process");
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
      }),
    onSuccess: () => {
      setName("");
      void queryClient.invalidateQueries({ queryKey: ["agents", orgId] });
    },
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    if (name.trim()) create.mutate();
  }
  return (
    <>
      <header className="page-header">
        <div><p className="eyebrow">Agents</p><h1>代理</h1></div>
        <OrgNavigation orgId={orgId} />
      </header>
      <div className="grid-two">
        <section className="panel">
          <h2>现有 Agent</h2>
          {agents.error && <ErrorNotice error={agents.error} />}
          <div className="list">
            {agents.data?.map((agent) => (
              <article className="row" key={agent.id}>
                <Link to={`/orgs/${orgId}/agents/${agent.id}`}>{agent.name}</Link>
                <Badge>{agent.role}</Badge>
                <Badge>{agent.status}</Badge>
              </article>
            ))}
          </div>
        </section>
        <form className="panel form" onSubmit={submit}>
          <h2>{isFirstAgent ? "创建 CEO" : "创建 Agent"}</h2>
          {isFirstAgent && <p className="muted">首个 Agent 将作为 CEO 创建</p>}
          <label>Agent 名称<input value={name} onChange={(event) => setName(event.target.value)} required /></label>
          <label>
            角色
            <select
              disabled={isFirstAgent}
              value={effectiveRole}
              onChange={(event) => setRole(event.target.value as AgentRole)}
            >
              {ROLES.map((item) => <option key={item}>{item}</option>)}
            </select>
          </label>
          <label>
            Runtime
            <select value={runtime} onChange={(event) => setRuntime(event.target.value as AgentRuntimeType)}>
              {RUNTIMES.map((item) => <option key={item}>{item}</option>)}
            </select>
          </label>
          {create.error && <ErrorNotice error={create.error} />}
          <button disabled={!agents.isSuccess || create.isPending} type="submit">
            {isFirstAgent ? "创建 CEO" : "新建 Agent"}
          </button>
        </form>
      </div>
    </>
  );
}
