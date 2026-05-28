import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { renderApp, respond } from "./render-app";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("controls an agent from its overview and shows runtime status", async () => {
  const agent = { id: "agent-1", orgId: "org-1", name: "Builder", role: "engineer", status: "idle", agentRuntimeType: "codex_local", agentRuntimeConfig: {}, runtimeConfig: {}, budgetMonthlyCents: 0 };
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/agents/agent-1" && init?.method === "GET") return respond(agent);
    if (path === "/api/agents/agent-1/runtime-state" && init?.method === "GET") {
      return respond({ lastRunStatus: "succeeded", sessionDisplayId: "session-1", totalInputTokens: 10, totalOutputTokens: 5, totalCostCents: 1 });
    }
    return respond({ ...agent, status: "paused" });
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/agents/agent-1");
  const heading = await screen.findByRole("heading", { name: "Builder" });
  const header = heading.closest("header");
  expect(header).not.toBeNull();
  expect(within(header!).getByText("idle")).toBeInTheDocument();
  expect(within(header!).getByRole("button", { name: "分配任务" })).toBeInTheDocument();
  expect(within(header!).getByRole("link", { name: "聊天" })).toHaveAttribute(
    "href",
    "/orgs/org-1/chats?agentId=agent-1",
  );
  expect(within(header!).getByRole("button", { name: "暂停" })).toBeInTheDocument();
  expect(within(header!).getByRole("button", { name: "恢复" })).toBeInTheDocument();
  expect(within(header!).getByRole("button", { name: "终止" })).toBeInTheDocument();
  expect(within(header!).getByRole("button", { name: "运行心跳" })).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "暂停" })).toHaveLength(1);
  expect(await screen.findByText("succeeded")).toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: "暂停" }));
  await userEvent.click(screen.getByRole("button", { name: "运行心跳" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/agents/agent-1/pause",
    expect.objectContaining({ method: "POST" }),
  );
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/agents/agent-1/heartbeat/invoke",
    expect.objectContaining({ method: "POST" }),
  );
});

it("assigns a task to the current agent from a modal", async () => {
  const agent = { id: "agent-1", orgId: "org-1", name: "Builder", role: "engineer", status: "idle", agentRuntimeType: "codex_local", agentRuntimeConfig: {}, runtimeConfig: {}, budgetMonthlyCents: 0 };
  const createdIssue = {
    id: "issue-1",
    orgId: "org-1",
    identifier: "CORE-1",
    title: "排查部署",
    status: "todo",
    priority: "medium",
    description: null,
    projectId: null,
    goalId: null,
    assigneeAgentId: "agent-1",
    assigneeUserId: null,
    originKind: "manual",
    originId: null,
    reviewerAgentId: null,
    reviewerUserId: null,
    parentId: null,
    issueNumber: 1,
    requestDepth: 0,
    startedAt: null,
    completedAt: null,
    createdAt: "2026-05-27T00:00:00Z",
    updatedAt: "2026-05-27T00:00:00Z",
  };
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/agents/agent-1" && init?.method === "GET") return respond(agent);
    if (path === "/api/agents/agent-1/runtime-state" && init?.method === "GET") {
      return respond({ lastRunStatus: null, sessionDisplayId: null, totalInputTokens: 0, totalOutputTokens: 0, totalCostCents: 0 });
    }
    if (path === "/api/orgs/org-1/issues" && init?.method === "POST") return respond(createdIssue, 201);
    if (path === "/api/issues/issue-1" && init?.method === "GET") return respond(createdIssue);
    if (path === "/api/issues/issue-1/comments" && init?.method === "GET") return respond([]);
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/agents/agent-1");
  await userEvent.click(await screen.findByRole("button", { name: "分配任务" }));
  const dialog = screen.getByRole("dialog", { name: "分配任务" });
  expect(dialog).toHaveTextContent("负责人：Builder");
  await userEvent.type(within(dialog).getByLabelText("任务标题"), "排查部署");
  await userEvent.click(within(dialog).getByRole("button", { name: "创建任务" }));

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/issues",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ title: "排查部署", assigneeAgentId: "agent-1" }),
    }),
  );
  expect(await screen.findByRole("heading", { name: "排查部署" })).toBeInTheDocument();
});

it("saves supported agent configuration and shows heartbeat runs tab", async () => {
  const agent = { id: "agent-1", orgId: "org-1", name: "Builder", role: "engineer", status: "idle", agentRuntimeType: "process", agentRuntimeConfig: {}, runtimeConfig: {}, budgetMonthlyCents: 0, capabilities: null, reportsTo: null };
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/agents/agent-1" && init?.method === "GET") return respond(agent);
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") return respond([agent]);
    if (path.includes("heartbeat-runs") && init?.method === "GET") {
      return respond([{ id: "run-1", status: "succeeded", invocationSource: "on_demand" }]);
    }
    return respond({ ...agent, name: "Builder 2" });
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/agents/agent-1/configuration");
  await userEvent.clear(await screen.findByLabelText("智能体名称"));
  await userEvent.type(screen.getByLabelText("智能体名称"), "Builder 2");
  await userEvent.selectOptions(screen.getByLabelText("Runtime"), "codex_local");
  await userEvent.clear(screen.getByLabelText("月度预算（cents）"));
  await userEvent.type(screen.getByLabelText("月度预算（cents）"), "1000");
  fireEvent.change(screen.getByLabelText("Agent runtime config"), { target: { value: '{"model":"gpt"}' } });
  await userEvent.click(screen.getByRole("button", { name: "保存配置" }));

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/agents/agent-1",
    expect.objectContaining({
      method: "PATCH",
      body: expect.stringContaining('"agentRuntimeType":"codex_local"'),
    }),
  );

  await userEvent.click(screen.getByRole("link", { name: "运行" }));
  expect(await screen.findByText("succeeded")).toBeInTheDocument();
});
