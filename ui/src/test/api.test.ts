import { afterEach, describe, expect, it, vi } from "vitest";
import { approvalsApi } from "../api/approvals";
import { agentsApi } from "../api/agents";
import { chatsApi } from "../api/chats";
import { heartbeatApi } from "../api/heartbeat";
import { issuesApi } from "../api/issues";
import { messengerApi } from "../api/messenger";
import { organizationSkillsApi } from "../api/organizationSkills";
import { organizationsApi } from "../api/organizations";
import { projectsApi } from "../api/projects";
import { request } from "../api/client";
import { runtimeProvidersApi } from "../api/runtimeProviders";
import { runIntelligenceApi } from "../api/runIntelligence";

function jsonResponse(body: unknown, status = 200): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

function streamResponse(events: unknown[], status = 201): Promise<Response> {
  return Promise.resolve(
    new Response(events.map((event) => JSON.stringify(event)).join("\n"), {
      status,
      headers: { "Content-Type": "application/x-ndjson" },
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("organization API", () => {
  it("lists organizations", async () => {
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(jsonResponse([{ id: "org-1", name: "Core" }]))
      .mockReturnValueOnce(jsonResponse({ id: "org-1", name: "Core", status: "archived" }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(organizationsApi.list()).resolves.toEqual([{ id: "org-1", name: "Core" }]);
    await organizationsApi.archive("org-1");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/orgs",
      expect.objectContaining({ method: "GET" }),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/orgs/org-1/archive",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("surfaces API error details", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockReturnValue(jsonResponse({ detail: "Board access required" }, 403)),
    );

    await expect(organizationsApi.list()).rejects.toMatchObject({
      status: 403,
      message: "Board access required",
    });
  });
});

describe("runtime provider API", () => {
  it("manages organization runtime providers and models", async () => {
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(jsonResponse([{ providerId: "kimi", runtimeType: "opencode_local" }]))
      .mockReturnValueOnce(jsonResponse({ providerId: "kimi", runtimeType: "opencode_local" }, 201))
      .mockReturnValueOnce(jsonResponse({ providerId: "kimi", enabled: false }))
      .mockReturnValueOnce(jsonResponse({ modelId: "kimi/k2", displayName: "Kimi K2" }))
      .mockReturnValueOnce(jsonResponse([{ modelId: "kimi/k2", displayName: "Kimi K2" }]))
      .mockReturnValueOnce(jsonResponse({ modelId: "kimi/k2", enabled: false }))
      .mockReturnValueOnce(jsonResponse({ modelId: "kimi/k2" }));
    vi.stubGlobal("fetch", fetchMock);

    await runtimeProvidersApi.listProviders("org-1", "opencode_local");
    await runtimeProvidersApi.createProvider("org-1", {
      runtimeType: "opencode_local",
      providerId: "kimi",
      name: "Kimi",
      protocol: "openai_chat_completions",
      baseUrl: "https://api.moonshot.cn/v1",
      apiKey: "secret",
      enabled: true,
    });
    await runtimeProvidersApi.updateProvider("org-1", "opencode_local", "kimi", { enabled: false });
    await runtimeProvidersApi.createModel("org-1", "opencode_local", "kimi", {
      modelId: "kimi/k2",
      displayName: "Kimi K2",
      enabled: true,
    });
    await runtimeProvidersApi.listModels("org-1", "opencode_local", "kimi");
    await runtimeProvidersApi.updateModel("org-1", "opencode_local", "kimi", "kimi/k2", { enabled: false });
    await runtimeProvidersApi.deleteModel("org-1", "opencode_local", "kimi", "kimi/k2");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/orgs/org-1/runtime-providers?runtimeType=opencode_local",
      expect.objectContaining({ method: "GET" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/orgs/org-1/runtime-providers",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          runtimeType: "opencode_local",
          providerId: "kimi",
          name: "Kimi",
          protocol: "openai_chat_completions",
          baseUrl: "https://api.moonshot.cn/v1",
          apiKey: "secret",
          enabled: true,
        }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "/api/orgs/org-1/runtime-providers/kimi?runtimeType=opencode_local",
      expect.objectContaining({ method: "PATCH", body: JSON.stringify({ enabled: false }) }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      "/api/orgs/org-1/runtime-providers/kimi/models?runtimeType=opencode_local",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ modelId: "kimi/k2", displayName: "Kimi K2", enabled: true }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      5,
      "/api/orgs/org-1/runtime-providers/kimi/models?runtimeType=opencode_local",
      expect.objectContaining({ method: "GET" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      6,
      "/api/orgs/org-1/runtime-providers/kimi/models/kimi%2Fk2?runtimeType=opencode_local",
      expect.objectContaining({ method: "PATCH", body: JSON.stringify({ enabled: false }) }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      7,
      "/api/orgs/org-1/runtime-providers/kimi/models/kimi%2Fk2?runtimeType=opencode_local",
      expect.objectContaining({ method: "DELETE" }),
    );
  });
});

describe("issue API", () => {
  it("filters the issue list and posts comments", async () => {
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(jsonResponse([]))
      .mockReturnValueOnce(jsonResponse({ id: "issue-1", assigneeAgentId: "agent-1" }))
      .mockReturnValueOnce(jsonResponse({ issueId: "issue-1", wakeReason: "issue_execute" }))
      .mockReturnValueOnce(jsonResponse({ id: "comment-1", body: "Ship it" }));
    vi.stubGlobal("fetch", fetchMock);

    await issuesApi.list("org-1", { status: "in_progress" });
    await issuesApi.checkout("issue-1", { agentId: "agent-1", expectedStatuses: ["todo"] });
    await issuesApi.heartbeatContext("issue-1");
    await issuesApi.addComment("issue-1", { body: "Ship it" });

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/orgs/org-1/issues?status=in_progress",
      expect.objectContaining({ method: "GET" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/issues/issue-1/checkout",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ agentId: "agent-1", expectedStatuses: ["todo"] }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "/api/issues/issue-1/heartbeat-context",
      expect.objectContaining({ method: "GET" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      "/api/issues/issue-1/comments",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ body: "Ship it" }),
      }),
    );
  });
});

describe("approval API", () => {
  it("posts approve and resubmit decisions", async () => {
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(jsonResponse([{ id: "issue-1" }]))
      .mockReturnValueOnce(jsonResponse([{ id: "comment-1", body: "看过了" }]))
      .mockReturnValueOnce(jsonResponse({ id: "comment-2", body: "继续" }, 201))
      .mockReturnValueOnce(jsonResponse({ id: "approval-1", status: "approved" }))
      .mockReturnValueOnce(jsonResponse({ id: "approval-1", status: "pending" }));
    vi.stubGlobal("fetch", fetchMock);

    await approvalsApi.listIssues("approval-1");
    await approvalsApi.listComments("approval-1");
    await approvalsApi.addComment("approval-1", { body: "继续" });
    await approvalsApi.approve("approval-1", "Looks correct");
    await approvalsApi.resubmit("approval-1", { payload: { revised: true } });

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/approvals/approval-1/issues",
      expect.objectContaining({ method: "GET" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/approvals/approval-1/comments",
      expect.objectContaining({ method: "GET" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "/api/approvals/approval-1/comments",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ body: "继续" }) }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      "/api/approvals/approval-1/approve",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      5,
      "/api/approvals/approval-1/resubmit",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ payload: { revised: true } }),
      }),
    );
  });
});

describe("project API", () => {
  it("creates projects and manages resource attachments", async () => {
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(jsonResponse({ id: "project-1", name: "Console" }, 201))
      .mockReturnValueOnce(jsonResponse({ id: "attachment-1", resourceId: "resource-1" }, 201))
      .mockReturnValueOnce(jsonResponse({ id: "attachment-1", role: "reference" }))
      .mockReturnValueOnce(jsonResponse({ id: "attachment-1" }));
    vi.stubGlobal("fetch", fetchMock);

    await projectsApi.create("org-1", { name: "Console", status: "planned" });
    await projectsApi.addResource("project-1", { resourceId: "resource-1", role: "working_set" });
    await projectsApi.updateResource("project-1", "attachment-1", { role: "reference" });
    await projectsApi.removeResource("project-1", "attachment-1");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/orgs/org-1/projects",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ name: "Console", status: "planned" }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/projects/project-1/resources",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      "/api/projects/project-1/resources/attachment-1",
      expect.objectContaining({ method: "DELETE" }),
    );
  });
});

describe("agent and heartbeat APIs", () => {
  it("creates, pauses and invokes an agent, then loads runs", async () => {
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(jsonResponse({ id: "agent-1" }, 201))
      .mockReturnValueOnce(jsonResponse({ id: "agent-1", status: "paused" }))
      .mockReturnValueOnce(jsonResponse({ id: "run-1", status: "succeeded" }, 202))
      .mockReturnValueOnce(jsonResponse([{ id: "run-1", status: "succeeded" }]))
      .mockReturnValueOnce(jsonResponse({ id: "run-1", status: "succeeded" }))
      .mockReturnValueOnce(jsonResponse([{ id: 1, runId: "run-1", eventType: "heartbeat.started" }]))
      .mockReturnValueOnce(jsonResponse({ content: "full log", nextOffset: 18, eof: true }))
      .mockReturnValueOnce(jsonResponse({ id: "run-1", status: "cancelled" }))
      .mockReturnValueOnce(jsonResponse({ id: "run-2", status: "queued", retryOfRunId: "run-1" }));
    vi.stubGlobal("fetch", fetchMock);

    await agentsApi.create("org-1", {
      name: "Builder",
      role: "engineer",
      agentRuntimeType: "process",
      agentRuntimeConfig: {},
    });
    await agentsApi.pause("agent-1");
    await heartbeatApi.invoke("agent-1", { idempotencyKey: "once", forceFreshSession: true, reason: "manual" });
    await heartbeatApi.list("org-1", "agent-1");
    await heartbeatApi.get("run-1");
    await heartbeatApi.listEvents("run-1", { afterSeq: 3, limit: 20 });
    await heartbeatApi.getWorkspaceOperationLog("operation-1", { offset: 10, limitBytes: 100 });
    await heartbeatApi.cancel("run-1");
    await heartbeatApi.retry("run-1");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/orgs/org-1/agents",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "/api/agents/agent-1/heartbeat/invoke",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ idempotencyKey: "once", forceFreshSession: true, reason: "manual" }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      "/api/orgs/org-1/heartbeat-runs?agentId=agent-1",
      expect.objectContaining({ method: "GET" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      5,
      "/api/heartbeat-runs/run-1",
      expect.objectContaining({ method: "GET" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      6,
      "/api/heartbeat-runs/run-1/events?afterSeq=3&limit=20",
      expect.objectContaining({ method: "GET" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      7,
      "/api/workspace-operations/operation-1/log?offset=10&limitBytes=100",
      expect.objectContaining({ method: "GET" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      8,
      "/api/heartbeat-runs/run-1/cancel",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      9,
      "/api/heartbeat-runs/run-1/retry",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("posts approval payload overrides and issue links", async () => {
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(jsonResponse({ id: "approval-1", status: "pending" }, 201))
      .mockReturnValueOnce(jsonResponse({ id: "approval-1", status: "approved" }))
      .mockReturnValueOnce(jsonResponse({ id: "approval-1", status: "pending" }));
    vi.stubGlobal("fetch", fetchMock);

    await approvalsApi.create("org-1", {
      type: "chat_issue_creation",
      payload: {},
      requestedByAgentId: "agent-1",
      issueIds: ["issue-1"],
    });
    await approvalsApi.approve("approval-1", { payload: { labels: ["backend"] } });
    await approvalsApi.resubmit("approval-1", { payload: {}, issueIds: ["issue-2"] });

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/orgs/org-1/approvals",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          type: "chat_issue_creation",
          payload: {},
          requestedByAgentId: "agent-1",
          issueIds: ["issue-1"],
        }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/approvals/approval-1/approve",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ payload: { labels: ["backend"] } }),
      }),
    );
  });

  it("covers agent configuration management routes", async () => {
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(jsonResponse({ name: "Builder" }))
      .mockReturnValueOnce(jsonResponse([]))
      .mockReturnValueOnce(jsonResponse({ id: "agent-1", runtimeConfig: {} }))
      .mockReturnValueOnce(jsonResponse([]))
      .mockReturnValueOnce(jsonResponse({ id: "revision-1" }))
      .mockReturnValueOnce(jsonResponse({ id: "agent-1" }))
      .mockReturnValueOnce(jsonResponse({ agentId: "agent-1" }))
      .mockReturnValueOnce(jsonResponse({ agentId: "agent-1", path: "soul.md" }))
      .mockReturnValueOnce(jsonResponse({ id: "agent-1", status: "terminated" }))
      .mockReturnValueOnce(jsonResponse({ id: "run-1", status: "queued" }, 202));
    vi.stubGlobal("fetch", fetchMock);

    await agentsApi.nameSuggestion("org-1");
    await agentsApi.configurations("org-1");
    await agentsApi.configuration("agent-1");
    await agentsApi.configRevisions("agent-1");
    await agentsApi.configRevision("agent-1", "revision-1");
    await agentsApi.rollbackConfigRevision("agent-1", "revision-1");
    await agentsApi.resetSession("agent-1", { taskKey: "task-1" });
    await agentsApi.updateInstructionsPath("agent-1", { path: "soul.md" });
    await agentsApi.archive("agent-1");
    await heartbeatApi.wakeup("agent-1", {
      source: "on_demand",
      triggerDetail: "manual",
      reason: "manual",
      payload: { requestedBy: "ui" },
      forceFreshSession: true,
    });

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/orgs/org-1/agents/name-suggestion",
      expect.objectContaining({ method: "GET" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      6,
      "/api/agents/agent-1/config-revisions/revision-1/rollback",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      7,
      "/api/agents/agent-1/runtime-state/reset-session",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ taskKey: "task-1" }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      8,
      "/api/agents/agent-1/instructions-path",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({ path: "soul.md" }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      9,
      "/api/agents/agent-1/archive",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      10,
      "/api/agents/agent-1/wakeup",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          source: "on_demand",
          triggerDetail: "manual",
          reason: "manual",
          payload: { requestedBy: "ui" },
          forceFreshSession: true,
        }),
      }),
    );
  });

  it("covers runtime adapter and skills management routes", async () => {
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(jsonResponse([{ id: "gpt-5", label: "GPT-5" }]))
      .mockReturnValueOnce(jsonResponse({ type: "codex_local", capabilities: { models: true } }))
      .mockReturnValueOnce(jsonResponse({ provider: "openai", ok: false, windows: [] }))
      .mockReturnValueOnce(jsonResponse({ agentRuntimeType: "http", status: "pass", checks: [] }))
      .mockReturnValueOnce(jsonResponse({ desiredSkills: [], entries: [] }))
      .mockReturnValueOnce(jsonResponse({ desiredSkills: ["review"], entries: [] }))
      .mockReturnValueOnce(jsonResponse({ desiredSkills: ["review", "debug"], entries: [] }))
      .mockReturnValueOnce(jsonResponse({ key: "private:incident" }, 201))
      .mockReturnValueOnce(jsonResponse({ totalCount: 0, skills: [] }));
    vi.stubGlobal("fetch", fetchMock);

    await agentsApi.adapterModels("org-1", "codex_local");
    await agentsApi.adapterMetadata("org-1", "codex_local");
    await agentsApi.adapterQuotaWindows("org-1", "codex_local");
    await agentsApi.testAdapterEnvironment("org-1", "http", { url: "https://example.test" });
    await agentsApi.skills("agent-1");
    await agentsApi.syncSkills("agent-1", ["review"]);
    await agentsApi.enableSkills("agent-1", ["debug"]);
    await agentsApi.createPrivateSkill("agent-1", { name: "Incident", markdown: "# Incident" });
    await agentsApi.skillsAnalytics("agent-1", 14);

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/orgs/org-1/adapters/codex_local/models",
      expect.objectContaining({ method: "GET" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      "/api/orgs/org-1/adapters/http/test-environment",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ agentRuntimeConfig: { url: "https://example.test" } }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      6,
      "/api/agents/agent-1/skills/sync",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ desiredSkills: ["review"] }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      9,
      "/api/agents/agent-1/skills/analytics?windowDays=14",
      expect.objectContaining({ method: "GET" }),
    );
  });
});

describe("run intelligence API", () => {
  it("loads run intelligence list, detail, events and log", async () => {
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(jsonResponse([{ id: "run-1" }]))
      .mockReturnValueOnce(jsonResponse({ id: "run-1" }))
      .mockReturnValueOnce(jsonResponse([{ seq: 1 }]))
      .mockReturnValueOnce(jsonResponse({ content: "raw log", eof: true }));
    vi.stubGlobal("fetch", fetchMock);

    await runIntelligenceApi.list("org-1", { runIdPrefix: "run", limit: 5 });
    await runIntelligenceApi.get("run-1");
    await runIntelligenceApi.events("run-1");
    await runIntelligenceApi.log("run-1");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/run-intelligence/orgs/org-1/runs?runIdPrefix=run&limit=5",
      expect.objectContaining({ method: "GET" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      "/api/run-intelligence/runs/run-1/log",
      expect.objectContaining({ method: "GET" }),
    );
  });
});

describe("organization skills API", () => {
  it("covers import, scan-local and install-update routes", async () => {
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(jsonResponse({ id: "skill-1" }, 201))
      .mockReturnValueOnce(jsonResponse({ candidates: [], imported: [] }))
      .mockReturnValueOnce(jsonResponse({ id: "skill-1" }));
    vi.stubGlobal("fetch", fetchMock);

    await organizationSkillsApi.import("org-1", {
      sourcePath: "D:/skills/review",
      slug: "review",
      overwrite: true,
    });
    await organizationSkillsApi.scanLocal("org-1", {
      rootPath: "D:/skills",
      importDiscovered: true,
    });
    await organizationSkillsApi.installUpdate("org-1", "skill-1");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/orgs/org-1/skills/import",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/orgs/org-1/skills/scan-local",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "/api/orgs/org-1/skills/skill-1/install-update",
      expect.objectContaining({ method: "POST" }),
    );
  });
});

describe("chat API", () => {
  it("creates a conversation and sends a message", async () => {
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(jsonResponse({ id: "chat-1", title: "Support" }, 201))
      .mockReturnValueOnce(jsonResponse({ messages: [{ body: "Ready" }] }, 201));
    vi.stubGlobal("fetch", fetchMock);

    await chatsApi.create("org-1", { title: "Support", preferredAgentId: "agent-1" });
    await chatsApi.addMessage("chat-1", { body: "Start" });

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/orgs/org-1/chats",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/chats/chat-1/messages",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ body: "Start" }),
      }),
    );
  });

  it("streams chat message events", async () => {
    const events: string[] = [];
    const fetchMock = vi.fn().mockReturnValueOnce(streamResponse([
      { type: "ack", userMessage: { id: "message-1", role: "user", body: "Start" } },
      { type: "assistant_delta", delta: "Re" },
      { type: "assistant_delta", delta: "ady" },
      { type: "final", messages: [{ id: "message-2", role: "assistant", body: "Ready" }] },
    ]));
    vi.stubGlobal("fetch", fetchMock);

    const result = await chatsApi.addMessageStream("chat-1", { body: "Start" }, (event) => {
      events.push(event.type);
    });

    expect(result.messages).toEqual([{ id: "message-2", role: "assistant", body: "Ready" }]);
    expect(events).toEqual(["ack", "assistant_delta", "assistant_delta", "final"]);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/chats/chat-1/messages/stream",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ body: "Start" }),
      }),
    );
  });

  it("shows the root cause for SQLAlchemy stream errors", async () => {
    const fetchMock = vi.fn().mockReturnValueOnce(streamResponse([
      {
        type: "error",
        error: "(sqlite3.OperationalError) database is locked\n[SQL: INSERT INTO chat_messages ...]\n(Background on this error at: https://sqlalche.me/e/20/e3q8)",
      },
    ]));
    vi.stubGlobal("fetch", fetchMock);

    await expect(chatsApi.addMessageStream("chat-1", { body: "Start" })).rejects.toThrow("database is locked");
  });

  it("shows the root cause for JSON API errors", async () => {
    const fetchMock = vi.fn().mockReturnValueOnce(jsonResponse(
      {
        detail: "(sqlite3.OperationalError) database is locked\n[SQL: INSERT INTO chat_messages ...]\n(Background on this error at: https://sqlalche.me/e/20/e3q8)",
      },
      500,
    ));
    vi.stubGlobal("fetch", fetchMock);

    await expect(request("/api/fails", { method: "GET" })).rejects.toThrow("database is locked");
  });

  it("covers Step 16 chat and messenger routes", async () => {
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(jsonResponse([]))
      .mockReturnValueOnce(jsonResponse({ id: "chat-1", isPinned: true }))
      .mockReturnValueOnce(jsonResponse({ id: "link-1" }, 201))
      .mockReturnValueOnce(jsonResponse({ id: "chat-1", primaryIssueId: "issue-1" }))
      .mockReturnValueOnce(jsonResponse({ issue: { id: "issue-1" } }, 201))
      .mockReturnValueOnce(jsonResponse({ message: { id: "message-1" } }, 201))
      .mockReturnValueOnce(jsonResponse({ stopped: true }))
      .mockReturnValueOnce(jsonResponse([{ threadKey: "chat:chat-1" }]))
      .mockReturnValueOnce(jsonResponse({ conversation: { id: "chat-1" }, messages: [] }))
      .mockReturnValueOnce(jsonResponse({ threadKey: "chat:chat-1", lastReadAt: "now" }));
    vi.stubGlobal("fetch", fetchMock);

    await chatsApi.list("org-1", { status: "archived", q: "deploy" });
    await chatsApi.updateUserState("chat-1", { pinned: true, unread: false });
    await chatsApi.addContextLink("chat-1", { entityType: "project", entityId: "project-1" });
    await chatsApi.setProjectContext("chat-1", "project-1");
    await chatsApi.convertToIssue("chat-1", { proposal: { title: "Ship", description: "Deploy" } });
    await chatsApi.resolveOperationProposal("chat-1", "message-1", { action: "approve" });
    await chatsApi.stopStream("chat-1");
    await messengerApi.threads("org-1");
    await messengerApi.chat("org-1", "chat-1");
    await messengerApi.read("org-1", "chat:chat-1");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/orgs/org-1/chats?status=archived&q=deploy",
      expect.objectContaining({ method: "GET" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/chats/chat-1/user-state",
      expect.objectContaining({ method: "PATCH", body: JSON.stringify({ pinned: true, unread: false }) }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      5,
      "/api/chats/chat-1/convert-to-issue",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ proposal: { title: "Ship", description: "Deploy" } }),
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      8,
      "/api/orgs/org-1/messenger/threads",
      expect.objectContaining({ method: "GET" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      10,
      "/api/orgs/org-1/messenger/threads/chat%3Achat-1/read",
      expect.objectContaining({ method: "POST", body: JSON.stringify({}) }),
    );
  });
});
