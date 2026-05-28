import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { agentsApi } from "../api/agents";
import { heartbeatApi } from "../api/heartbeat";
import { Badge } from "../components/Badge";
import { ErrorNotice } from "../components/ErrorNotice";
import { OrgWorkspace } from "./OrganizationPage";
import { useParams } from "react-router-dom";

export function HeartbeatRunsPage() {
  const { orgId = "" } = useParams();
  const [agentId, setAgentId] = useState("");
  const [selectedRunId, setSelectedRunId] = useState("");
  const agents = useQuery({ queryKey: ["agents", orgId], queryFn: () => agentsApi.list(orgId) });
  const runs = useQuery({
    queryKey: ["heartbeat-runs", orgId, agentId],
    queryFn: () => heartbeatApi.list(orgId, agentId || undefined),
  });
  const detail = useQuery({
    queryKey: ["heartbeat-run", selectedRunId],
    queryFn: () => heartbeatApi.get(selectedRunId),
    enabled: Boolean(selectedRunId),
  });
  const events = useQuery({
    queryKey: ["heartbeat-run-events", selectedRunId],
    queryFn: () => heartbeatApi.listEvents(selectedRunId),
    enabled: Boolean(selectedRunId),
  });
  const agentList = Array.isArray(agents.data) ? agents.data : [];
  const agentNameById = new Map(agentList.map((agent) => [agent.id, agent.name]));

  useEffect(() => {
    setSelectedRunId("");
  }, [agentId]);

  return (
    <OrgWorkspace orgId={orgId}>
      <header className="page-header">
        <div><p className="eyebrow">Organization</p><h1>心跳</h1></div>
      </header>
      <label className="heartbeat-filter">
        智能体筛选
        <select value={agentId} onChange={(event) => setAgentId(event.target.value)}>
          <option value="">全部智能体</option>
          {agentList.map((agent) => <option key={agent.id} value={agent.id}>{agent.name}</option>)}
        </select>
      </label>
      {agents.error && <ErrorNotice error={agents.error} />}
      {runs.error && <ErrorNotice error={runs.error} />}
      <div className="heartbeat-layout">
        <section className="panel heartbeat-runs">
          <h2>运行记录</h2>
          {runs.isSuccess && runs.data.length === 0 && <p className="muted">暂无心跳运行记录。</p>}
          {runs.data?.map((run) => (
            <button
              aria-label={`${run.id} ${agentNameById.get(run.agentId) ?? run.agentId} ${run.status}`}
              className={`heartbeat-run ${selectedRunId === run.id ? "selected" : ""}`}
              key={run.id}
              onClick={() => setSelectedRunId(run.id)}
              type="button"
            >
              <span>
                <strong>{agentNameById.get(run.agentId) ?? run.agentId}</strong>
                <small>{run.id}</small>
              </span>
              <Badge>{run.status}</Badge>
            </button>
          ))}
        </section>
        <section className="panel heartbeat-detail">
          <h2>运行详情</h2>
          {!selectedRunId && <p className="muted">选择一条运行记录查看事件。</p>}
          {detail.error && <ErrorNotice error={detail.error} />}
          {events.error && <ErrorNotice error={events.error} />}
          {detail.data && (
            <div className="meta-line">
              <Badge>{detail.data.status}</Badge>
              <Badge>{detail.data.invocationSource}</Badge>
            </div>
          )}
          {detail.data?.error && <p className="error-notice">{detail.data.error}</p>}
          <div className="heartbeat-events">
            {events.data?.map((event) => (
              <article className="heartbeat-event" key={event.id}>
                <strong>{event.eventType}</strong>
                <span>{event.message ?? "无消息"}</span>
              </article>
            ))}
          </div>
        </section>
      </div>
    </OrgWorkspace>
  );
}
