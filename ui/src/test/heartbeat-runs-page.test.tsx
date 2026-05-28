import { cleanup, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { renderApp, respond } from "./render-app";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("filters organization heartbeat runs and opens their event detail", async () => {
  const run = {
    id: "run-1",
    orgId: "org-1",
    agentId: "agent-1",
    invocationSource: "on_demand",
    status: "running",
    createdAt: "2026-05-27T08:00:00",
    error: null,
    retryOfRunId: null,
    processPid: 123,
    stdoutExcerpt: "adapter-ok",
    contextSnapshot: {
      executionWorkspaceId: "exec-1",
      projectWorkspaceId: "workspace-1",
      workspace: {
        rudderWorkspace: {
          id: "exec-1",
          name: "Issue workspace",
          cwd: "D:/coding/octopus/.octopus/workspaces/org-1/exec-1",
          status: "open",
          branchName: "issue/OCT-1",
        },
        env: {
          RUDDER_WORKSPACE_ID: "exec-1",
        },
      },
    },
  };
  const retriedRun = { ...run, id: "run-2", status: "queued", retryOfRunId: "run-1" };
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs" && init?.method === "GET") {
      return respond([{ id: "org-1", name: "核心团队", status: "active" }]);
    }
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([{ id: "agent-1", name: "Builder", role: "engineer", status: "idle" }]);
    }
    if (path.startsWith("/api/orgs/org-1/heartbeat-runs") && init?.method === "GET") return respond([run]);
    if (path === "/api/heartbeat-runs/run-1" && init?.method === "GET") return respond(run);
    if (path === "/api/heartbeat-runs/run-1/events?afterSeq=0&limit=200" && init?.method === "GET") {
      return respond([{ id: 1, runId: "run-1", agentId: "agent-1", seq: 1, eventType: "heartbeat.started", message: "Started", createdAt: "2026-05-27T08:00:00" }]);
    }
    if (path === "/api/heartbeat-runs/run-1/events?afterSeq=1&limit=20" && init?.method === "GET") {
      return respond([{ id: 2, runId: "run-1", agentId: "agent-1", seq: 2, eventType: "heartbeat.finished", message: "Finished", createdAt: "2026-05-27T08:00:01" }]);
    }
    if (path === "/api/heartbeat-runs/run-1/cancel" && init?.method === "POST") return respond({ ...run, status: "cancelled" });
    if (path === "/api/heartbeat-runs/run-1/retry" && init?.method === "POST") return respond(retriedRun, 202);
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/heartbeat-runs");

  expect(await screen.findByRole("heading", { name: "心跳" })).toBeInTheDocument();
  expect(await screen.findByRole("option", { name: "Builder" })).toBeInTheDocument();
  await userEvent.selectOptions(screen.getByLabelText("智能体筛选"), "agent-1");
  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/orgs/org-1/heartbeat-runs?agentId=agent-1",
      expect.objectContaining({ method: "GET" }),
    );
  });
  await userEvent.click(screen.getByRole("button", { name: /run-1/ }));
  expect(await screen.findByText("heartbeat.started")).toBeInTheDocument();
  expect(screen.getByText("Started")).toBeInTheDocument();
  expect(screen.getByText("PID 123")).toBeInTheDocument();
  expect(screen.getByText("执行工作区")).toBeInTheDocument();
  expect(screen.getByText("exec-1")).toBeInTheDocument();
  expect(screen.getByText("issue/OCT-1")).toBeInTheDocument();
  expect(screen.getByText("adapter-ok")).toBeInTheDocument();

  await userEvent.clear(screen.getByLabelText("afterSeq"));
  await userEvent.type(screen.getByLabelText("afterSeq"), "1");
  await userEvent.clear(screen.getByLabelText("limit"));
  await userEvent.type(screen.getByLabelText("limit"), "20");
  await userEvent.click(screen.getByRole("button", { name: "刷新事件" }));
  expect(await screen.findByText("heartbeat.finished")).toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: "取消运行" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
    "/api/heartbeat-runs/run-1/cancel",
    expect.objectContaining({ method: "POST" }),
  ));
  await userEvent.click(screen.getByRole("button", { name: "重试运行" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
    "/api/heartbeat-runs/run-1/retry",
    expect.objectContaining({ method: "POST" }),
  ));
});

it("shows an empty state when an organization has no heartbeat runs", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-empty/heartbeat-runs" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-empty/agents" && init?.method === "GET") return respond([]);
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-empty/heartbeat-runs");

  expect(await screen.findByText("暂无心跳运行记录。")).toBeInTheDocument();
});
