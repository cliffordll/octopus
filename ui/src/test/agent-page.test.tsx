import { cleanup, fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { renderApp, respond } from "./render-app";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("controls an agent from its overview and shows runtime status", async () => {
  const agent = { id: "agent-1", orgId: "org-1", name: "Builder", role: "engineer", status: "idle", agentRuntimeType: "process", agentRuntimeConfig: {}, runtimeConfig: {}, budgetMonthlyCents: 0 };
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/agents/agent-1" && init?.method === "GET") return respond(agent);
    if (path === "/api/agents/agent-1/runtime-state" && init?.method === "GET") {
      return respond({ lastRunStatus: "succeeded", sessionDisplayId: "session-1", totalInputTokens: 10, totalOutputTokens: 5, totalCostCents: 1 });
    }
    return respond({ ...agent, status: "paused" });
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/agents/agent-1");
  expect(await screen.findByRole("heading", { name: "Builder" })).toBeInTheDocument();
  expect(await screen.findByText("succeeded")).toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: "暂停" }));
  await userEvent.click(screen.getByRole("button", { name: "触发 Heartbeat" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/agents/agent-1/pause",
    expect.objectContaining({ method: "POST" }),
  );
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/agents/agent-1/heartbeat/invoke",
    expect.objectContaining({ method: "POST" }),
  );
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
