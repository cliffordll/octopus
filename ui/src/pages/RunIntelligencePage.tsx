import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { runIntelligenceApi, type RunIntelligenceRecord } from "../api/runIntelligence";
import { Badge } from "../components/Badge";
import { ErrorNotice } from "../components/ErrorNotice";
import { OrgWorkspace } from "./OrganizationPage";

function text(value: unknown): string {
  if (value === null || value === undefined) return "-";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

function runId(run: RunIntelligenceRecord): string {
  const value = run.id ?? run.runId;
  return typeof value === "string" ? value : "";
}

export function RunIntelligencePage() {
  const { orgId = "" } = useParams();
  const [runPrefix, setRunPrefix] = useState("");
  const [selectedRunId, setSelectedRunId] = useState("");
  const runs = useQuery({
    queryKey: ["run-intelligence", orgId, runPrefix],
    queryFn: () => runIntelligenceApi.list(orgId, { ...(runPrefix.trim() ? { runIdPrefix: runPrefix.trim() } : {}), limit: 50 }),
  });
  const detail = useQuery({
    queryKey: ["run-intelligence-detail", selectedRunId],
    queryFn: () => runIntelligenceApi.get(selectedRunId),
    enabled: Boolean(selectedRunId),
  });
  const events = useQuery({
    queryKey: ["run-intelligence-events", selectedRunId],
    queryFn: () => runIntelligenceApi.events(selectedRunId),
    enabled: Boolean(selectedRunId),
  });
  const log = useQuery({
    queryKey: ["run-intelligence-log", selectedRunId],
    queryFn: () => runIntelligenceApi.log(selectedRunId),
    enabled: Boolean(selectedRunId),
  });

  return (
    <OrgWorkspace contentClassName="org-content-full" orgId={orgId}>
      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Run Intelligence</p>
            <h1>运行分析</h1>
          </div>
          <Link className="button secondary small-button" to={`/orgs/${orgId}/heartbeat-runs`}>返回心跳</Link>
        </div>
        <label>
          Run ID 前缀
          <input value={runPrefix} onChange={(event) => setRunPrefix(event.target.value)} placeholder="输入 run id 前缀过滤" />
        </label>
        {runs.error && <ErrorNotice error={runs.error} />}
        {runs.isLoading && <p className="muted">加载运行列表中...</p>}
        <div className="agent-run-events">
          {(runs.data ?? []).map((run) => {
            const id = runId(run);
            const status = text(run.status);
            const runtime = text(run.agentRuntimeType);
            return (
              <article className="agent-run-event" key={id || JSON.stringify(run)}>
                <div className="agent-run-event-header">
                  <strong>{id || "unknown"}</strong>
                  {status !== "-" && <Badge>{status}</Badge>}
                  {runtime !== "-" && <Badge>{runtime}</Badge>}
                </div>
                <p className="muted">{text(run.agentName ?? run.agentId)} · {text(run.createdAt ?? run.startedAt)}</p>
                {id && <button className="secondary small-button" type="button" onClick={() => setSelectedRunId(id)}>查看详情</button>}
              </article>
            );
          })}
        </div>
      </section>
      {selectedRunId && (
        <section className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Run Detail</p>
              <h2>{selectedRunId}</h2>
            </div>
          </div>
          {detail.error && <ErrorNotice error={detail.error} />}
          {events.error && <ErrorNotice error={events.error} />}
          {log.error && <ErrorNotice error={log.error} />}
          {detail.data && <pre className="agent-run-json">{JSON.stringify(detail.data, null, 2)}</pre>}
          <h3>事件</h3>
          {(events.data ?? []).map((event, index) => (
            <pre className="issue-run-event-log" key={index}>{JSON.stringify(event, null, 2)}</pre>
          ))}
          <h3>日志</h3>
          {log.data?.content && <pre className="issue-run-event-log">{log.data.content}</pre>}
        </section>
      )}
    </OrgWorkspace>
  );
}
