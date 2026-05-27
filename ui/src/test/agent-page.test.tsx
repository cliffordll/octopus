import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { renderApp, respond } from "./render-app";

afterEach(() => {
  vi.unstubAllGlobals();
});

it("controls an agent and shows heartbeat runs", async () => {
  const agent = { id: "agent-1", orgId: "org-1", name: "Builder", role: "engineer", status: "idle", agentRuntimeType: "process" };
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/agents/agent-1" && init?.method === "GET") return respond(agent);
    if (path.includes("heartbeat-runs") && init?.method === "GET") {
      return respond([{ id: "run-1", status: "succeeded", invocationSource: "on_demand" }]);
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
