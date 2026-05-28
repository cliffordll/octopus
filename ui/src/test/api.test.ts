import { afterEach, describe, expect, it, vi } from "vitest";
import { approvalsApi } from "../api/approvals";
import { agentsApi } from "../api/agents";
import { chatsApi } from "../api/chats";
import { heartbeatApi } from "../api/heartbeat";
import { issuesApi } from "../api/issues";
import { organizationsApi } from "../api/organizations";
import { projectsApi } from "../api/projects";

function jsonResponse(body: unknown, status = 200): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("organization API", () => {
  it("lists organizations", async () => {
    const fetchMock = vi.fn().mockReturnValue(jsonResponse([{ id: "org-1", name: "Core" }]));
    vi.stubGlobal("fetch", fetchMock);

    await expect(organizationsApi.list()).resolves.toEqual([{ id: "org-1", name: "Core" }]);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/orgs",
      expect.objectContaining({ method: "GET" }),
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

describe("issue API", () => {
  it("filters the issue list and posts comments", async () => {
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(jsonResponse([]))
      .mockReturnValueOnce(jsonResponse({ id: "comment-1", body: "Ship it" }));
    vi.stubGlobal("fetch", fetchMock);

    await issuesApi.list("org-1", { status: "in_progress" });
    await issuesApi.addComment("issue-1", { body: "Ship it" });

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/orgs/org-1/issues?status=in_progress",
      expect.objectContaining({ method: "GET" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
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
      .mockReturnValueOnce(jsonResponse({ id: "approval-1", status: "approved" }))
      .mockReturnValueOnce(jsonResponse({ id: "approval-1", status: "pending" }));
    vi.stubGlobal("fetch", fetchMock);

    await approvalsApi.approve("approval-1", "Looks correct");
    await approvalsApi.resubmit("approval-1", { payload: { revised: true } });

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/approvals/approval-1/approve",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
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
      "/api/heartbeat-runs/run-1/cancel",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      8,
      "/api/heartbeat-runs/run-1/retry",
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
});
