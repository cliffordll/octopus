import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { agentsApi } from "../api/agents";
import { heartbeatApi } from "../api/heartbeat";
import { Badge } from "../components/Badge";
import { ErrorNotice } from "../components/ErrorNotice";
import { OrgWorkspace } from "./OrganizationPage";
import { useParams } from "react-router-dom";

export function HeartbeatRunsPage() {
  const { orgId = "" } = useParams();
  const queryClient = useQueryClient();
  const [agentId, setAgentId] = useState("");
  const [selectedRunId, setSelectedRunId] = useState("");
  const [afterSeq, setAfterSeq] = useState("0");
  const [eventLimit, setEventLimit] = useState("200");
  const eventAfterSeq = Number(afterSeq) || 0;
  const eventLimitValue = Number(eventLimit) || 1;
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
    queryKey: ["heartbeat-run-events", selectedRunId, eventAfterSeq, eventLimitValue],
    queryFn: () => heartbeatApi.listEvents(selectedRunId, { afterSeq: eventAfterSeq, limit: eventLimitValue }),
    enabled: Boolean(selectedRunId),
  });
  const cancelRun = useMutation({
    mutationFn: (runId: string) => heartbeatApi.cancel(runId),
    onSuccess: async (run) => {
      queryClient.setQueryData(["heartbeat-run", run.id], run);
      await queryClient.invalidateQueries({ queryKey: ["heartbeat-runs", orgId] });
      await queryClient.invalidateQueries({ queryKey: ["heartbeat-run-events", run.id] });
    },
  });
  const retryRun = useMutation({
    mutationFn: (runId: string) => heartbeatApi.retry(runId),
    onSuccess: async (run) => {
      queryClient.setQueryData(["heartbeat-run", run.id], run);
      await queryClient.invalidateQueries({ queryKey: ["heartbeat-runs", orgId] });
      setSelectedRunId(run.id);
    },
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
      {cancelRun.error && <ErrorNotice error={cancelRun.error} />}
      {retryRun.error && <ErrorNotice error={retryRun.error} />}
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
            <div className="heartbeat-detail-summary">
              <div className="meta-line">
                <Badge>{detail.data.status}</Badge>
                <Badge>{detail.data.invocationSource}</Badge>
                {detail.data.triggerDetail && <Badge>{detail.data.triggerDetail}</Badge>}
                {detail.data.processPid && <Badge>PID {detail.data.processPid}</Badge>}
              </div>
              <div className="actions">
                <button
                  disabled={cancelRun.isPending || !["queued", "running"].includes(detail.data.status)}
                  onClick={() => cancelRun.mutate(detail.data.id)}
                  type="button"
                >
                  取消运行
                </button>
                <button
                  disabled={retryRun.isPending || !["failed", "cancelled", "timed_out"].includes(detail.data.status)}
                  onClick={() => retryRun.mutate(detail.data.id)}
                  type="button"
                >
                  重试运行
                </button>
              </div>
              <dl className="detail-grid compact">
                <div><dt>重试来源</dt><dd>{detail.data.retryOfRunId ?? "无"}</dd></div>
                <div><dt>退出码</dt><dd>{detail.data.exitCode ?? "无"}</dd></div>
                <div><dt>开始时间</dt><dd>{detail.data.startedAt ?? "未开始"}</dd></div>
                <div><dt>结束时间</dt><dd>{detail.data.finishedAt ?? "未结束"}</dd></div>
              </dl>
            </div>
          )}
          {detail.data?.error && <p className="error-notice">{detail.data.error}</p>}
          {detail.data?.stdoutExcerpt && <pre className="run-excerpt">{detail.data.stdoutExcerpt}</pre>}
          {detail.data?.stderrExcerpt && <pre className="run-excerpt error">{detail.data.stderrExcerpt}</pre>}
          {selectedRunId && (
            <div className="heartbeat-event-controls">
              <label>afterSeq
                <input min="0" type="number" value={afterSeq} onChange={(event) => setAfterSeq(event.target.value)} />
              </label>
              <label>limit
                <input min="1" type="number" value={eventLimit} onChange={(event) => setEventLimit(event.target.value)} />
              </label>
              <button type="button" onClick={() => void events.refetch()}>刷新事件</button>
            </div>
          )}
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
