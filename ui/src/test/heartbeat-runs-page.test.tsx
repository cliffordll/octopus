import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { renderApp, respond } from "./render-app";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("shows organization heartbeats by agent and supports heartbeat actions", async () => {
  const run = {
    id: "run-1",
    orgId: "org-1",
    agentId: "agent-1",
    invocationSource: "on_demand",
    status: "running",
    createdAt: "2026-05-27T08:00:00",
    error: null,
    resultJson: { summary: "检查运行状态" },
  };
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([{
        id: "agent-1",
        orgId: "org-1",
        name: "Builder",
        urlKey: "builder",
        role: "engineer",
        title: "Engineer",
        status: "idle",
        agentRuntimeType: "codex_local",
        agentRuntimeConfig: { heartbeat: { enabled: true, intervalSec: 60 } },
        budgetMonthlyCents: 0,
        lastHeartbeatAt: "2026-05-27T07:00:00",
      }]);
    }
    if (path === "/api/orgs/org-1/heartbeat-runs" && init?.method === "GET") return respond([run]);
    if (path === "/api/agents/agent-1" && init?.method === "PATCH") {
      return respond({ id: "agent-1", orgId: "org-1", name: "Builder", status: "idle" });
    }
    if (path === "/api/agents/agent-1/heartbeat/invoke" && init?.method === "POST") {
      return respond({ ...run, id: "run-2", status: "queued" }, 202);
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/heartbeat-runs");

  expect(await screen.findByRole("heading", { name: "智能体" })).toBeInTheDocument();
  const row = await screen.findByTestId("org-heartbeat-row");
  expect(within(row).getByRole("link", { name: "Builder" })).toBeInTheDocument();
  expect(within(row).getByText("scheduled")).toBeInTheDocument();
  expect(within(row).getByText("running")).toBeInTheDocument();
  expect(within(row).getByText("检查运行状态")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "最近活动" })).toBeInTheDocument();

  await userEvent.click(within(row).getByRole("button", { name: "关闭" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
    "/api/agents/agent-1",
    expect.objectContaining({
      method: "PATCH",
      body: JSON.stringify({ agentRuntimeConfig: { heartbeat: { enabled: false, intervalSec: 60 } } }),
    }),
  ));

  await userEvent.click(within(row).getByRole("button", { name: "立即运行" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
    "/api/agents/agent-1/heartbeat/invoke",
    expect.objectContaining({ method: "POST" }),
  ));
});

it("shows empty states when an organization has no heartbeat data", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-empty/heartbeat-runs" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-empty/agents" && init?.method === "GET") return respond([]);
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-empty/heartbeat-runs");

  expect(await screen.findByText("暂无活跃智能体。创建智能体后再管理组织心跳。")).toBeInTheDocument();
  expect(await screen.findByText("暂无心跳运行记录。")).toBeInTheDocument();
});
