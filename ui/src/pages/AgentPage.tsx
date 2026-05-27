import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { agentsApi } from "../api/agents";
import { heartbeatApi } from "../api/heartbeat";
import { Badge } from "../components/Badge";
import { AgentsWorkspace } from "../components/ContextWorkspace";
import { ErrorNotice } from "../components/ErrorNotice";

export function AgentPage() {
  const { orgId = "", agentId = "" } = useParams();
  const queryClient = useQueryClient();
  const agent = useQuery({ queryKey: ["agent", agentId], queryFn: () => agentsApi.get(agentId) });
  const runs = useQuery({
    queryKey: ["heartbeat-runs", orgId, agentId],
    queryFn: () => heartbeatApi.list(orgId, agentId),
  });
  const action = useMutation({
    mutationFn: (operation: "pause" | "resume" | "terminate") => agentsApi[operation](agentId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["agent", agentId] }),
  });
  const invoke = useMutation({
    mutationFn: () => heartbeatApi.invoke(agentId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["heartbeat-runs", orgId, agentId] }),
  });
  if (agent.error) return <ErrorNotice error={agent.error} />;
  return (
    <AgentsWorkspace orgId={orgId}>
      <header className="page-header">
        <div>
          <Link className="back-link" to={`/orgs/${orgId}/agents`}>返回 Agents</Link>
          <h1>{agent.data?.name ?? "载入中..."}</h1>
        </div>
      </header>
      {agent.data && (
        <div className="grid-two detail-grid">
          <section className="panel">
            <div className="meta-line">
              <Badge>{agent.data.role}</Badge><Badge>{agent.data.status}</Badge><Badge>{agent.data.agentRuntimeType}</Badge>
            </div>
            <div className="actions">
              <button type="button" onClick={() => action.mutate("pause")}>暂停</button>
              <button className="secondary" type="button" onClick={() => action.mutate("resume")}>恢复</button>
              <button className="danger" type="button" onClick={() => action.mutate("terminate")}>终止</button>
            </div>
            <button type="button" onClick={() => invoke.mutate()}>触发 Heartbeat</button>
            {action.error && <ErrorNotice error={action.error} />}
            {invoke.error && <ErrorNotice error={invoke.error} />}
          </section>
          <section className="panel">
            <h2>Heartbeat Runs</h2>
            {runs.error && <ErrorNotice error={runs.error} />}
            <div className="list">
              {runs.data?.map((run) => (
                <article className="row" key={run.id}>
                  <span>{run.invocationSource}</span>
                  <Badge>{run.status}</Badge>
                </article>
              ))}
            </div>
          </section>
        </div>
      )}
    </AgentsWorkspace>
  );
}
