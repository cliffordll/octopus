import { jsonRequest, request } from "./client";
import type { HeartbeatRun, HeartbeatRunEvent, LogReadResult, WakeAgentPayload, WorkspaceOperation } from "./types";

interface EventOptions {
  afterSeq?: number;
  limit?: number;
}

interface LogOptions {
  limitBytes?: number;
  offset?: number;
}

interface StreamOptions {
  afterSeq?: number;
  offset?: number;
  limitBytes?: number;
  pollMs?: number;
  signal?: AbortSignal;
  onRun?: (run: HeartbeatRun) => void;
  onEvent?: (event: HeartbeatRunEvent) => void;
  onLog?: (payload: { content: string; nextOffset?: number; eof?: boolean }) => void;
  onFinal?: (run: HeartbeatRun) => void;
  onError?: (error: string) => void;
}

async function readNdjsonStream(response: Response, onLine: (value: unknown) => void): Promise<void> {
  const reader = response.body?.getReader();
  if (!reader) return;
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    let newlineIndex = buffer.indexOf("\n");
    while (newlineIndex >= 0) {
      const line = buffer.slice(0, newlineIndex).trim();
      buffer = buffer.slice(newlineIndex + 1);
      if (line) onLine(JSON.parse(line));
      newlineIndex = buffer.indexOf("\n");
    }
    if (done) break;
  }
  const rest = buffer.trim();
  if (rest) onLine(JSON.parse(rest));
}

export const heartbeatApi = {
  wakeup: (agentId: string, options: WakeAgentPayload = {}): Promise<HeartbeatRun> =>
    jsonRequest<HeartbeatRun>(
      `/api/agents/${encodeURIComponent(agentId)}/wakeup`,
      "POST",
      options,
    ),
  invoke: (agentId: string, options: WakeAgentPayload = {}): Promise<HeartbeatRun> =>
    jsonRequest<HeartbeatRun>(
      `/api/agents/${encodeURIComponent(agentId)}/heartbeat/invoke`,
      "POST",
      options,
    ),
  list: (orgId: string, agentId?: string): Promise<HeartbeatRun[]> => {
    const query = agentId ? `?agentId=${encodeURIComponent(agentId)}` : "";
    return request<HeartbeatRun[]>(
      `/api/orgs/${encodeURIComponent(orgId)}/heartbeat-runs${query}`,
      { method: "GET" },
    );
  },
  get: (runId: string): Promise<HeartbeatRun> =>
    request<HeartbeatRun>(`/api/heartbeat-runs/${encodeURIComponent(runId)}`, { method: "GET" }),
  listEvents: (runId: string, options: EventOptions = {}): Promise<HeartbeatRunEvent[]> => {
    const params = new URLSearchParams();
    if (options.afterSeq !== undefined) params.set("afterSeq", String(options.afterSeq));
    if (options.limit !== undefined) params.set("limit", String(options.limit));
    const query = params.size > 0 ? `?${params.toString()}` : "";
    return request<HeartbeatRunEvent[]>(`/api/heartbeat-runs/${encodeURIComponent(runId)}/events${query}`, {
      method: "GET",
    });
  },
  getLog: (runId: string, options: LogOptions = {}): Promise<LogReadResult> => {
    const params = new URLSearchParams();
    if (options.offset !== undefined) params.set("offset", String(options.offset));
    if (options.limitBytes !== undefined) params.set("limitBytes", String(options.limitBytes));
    const query = params.size > 0 ? `?${params.toString()}` : "";
    return request<LogReadResult>(`/api/heartbeat-runs/${encodeURIComponent(runId)}/log${query}`, {
      method: "GET",
    });
  },
  streamRun: async (runId: string, options: StreamOptions = {}): Promise<void> => {
    const params = new URLSearchParams();
    if (options.afterSeq !== undefined) params.set("afterSeq", String(options.afterSeq));
    if (options.offset !== undefined) params.set("offset", String(options.offset));
    if (options.limitBytes !== undefined) params.set("limitBytes", String(options.limitBytes));
    if (options.pollMs !== undefined) params.set("pollMs", String(options.pollMs));
    const query = params.size > 0 ? `?${params.toString()}` : "";
    const response = await fetch(`/api/heartbeat-runs/${encodeURIComponent(runId)}/stream${query}`, {
      method: "GET",
      signal: options.signal,
    });
    if (!response.ok) throw new Error(`Request failed (${response.status})`);
    await readNdjsonStream(response, (value) => {
      if (!value || typeof value !== "object") return;
      const event = value as Record<string, unknown>;
      if (event.type === "run" && event.run && typeof event.run === "object") {
        options.onRun?.(event.run as HeartbeatRun);
      }
      if (event.type === "event" && event.event && typeof event.event === "object") {
        options.onEvent?.(event.event as HeartbeatRunEvent);
      }
      if (event.type === "log" && typeof event.content === "string") {
        options.onLog?.({
          content: event.content,
          nextOffset: typeof event.nextOffset === "number" ? event.nextOffset : undefined,
          eof: typeof event.eof === "boolean" ? event.eof : undefined,
        });
      }
      if (event.type === "final" && event.run && typeof event.run === "object") {
        options.onFinal?.(event.run as HeartbeatRun);
      }
      if (event.type === "error") {
        options.onError?.(typeof event.error === "string" ? event.error : "Run stream error");
      }
    });
  },
  listWorkspaceOperations: (runId: string): Promise<WorkspaceOperation[]> =>
    request<WorkspaceOperation[]>(`/api/heartbeat-runs/${encodeURIComponent(runId)}/workspace-operations`, {
      method: "GET",
    }),
  getWorkspaceOperationLog: (operationId: string, options: LogOptions = {}): Promise<LogReadResult> => {
    const params = new URLSearchParams();
    if (options.offset !== undefined) params.set("offset", String(options.offset));
    if (options.limitBytes !== undefined) params.set("limitBytes", String(options.limitBytes));
    const query = params.size > 0 ? `?${params.toString()}` : "";
    return request<LogReadResult>(`/api/workspace-operations/${encodeURIComponent(operationId)}/log${query}`, {
      method: "GET",
    });
  },
  cancel: (runId: string): Promise<HeartbeatRun> =>
    jsonRequest<HeartbeatRun>(`/api/heartbeat-runs/${encodeURIComponent(runId)}/cancel`, "POST", {}),
  retry: (runId: string): Promise<HeartbeatRun> =>
    jsonRequest<HeartbeatRun>(`/api/heartbeat-runs/${encodeURIComponent(runId)}/retry`, "POST", {}),
};
