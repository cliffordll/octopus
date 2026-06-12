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
    issueId: "issue-1",
    issueIdentifier: "OCT-1",
    issueTitle: "检查运行状态",
    invocationSource: "automation",
    triggerDetail: "issue_passive_followup",
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
        agentRuntimeConfig: { model: "openai/gpt-5" },
        runtimeConfig: { heartbeat: { enabled: true, intervalSec: 60, wakeOnDemand: true } },
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
  expect(within(row).getByText("已调度")).toBeInTheDocument();
  expect(within(row).getByText("运行中")).toBeInTheDocument();
  expect(within(row).getByText("检查运行状态")).toBeInTheDocument();
  expect(screen.getByText("automation · issue_passive_followup")).toBeInTheDocument();
  expect(screen.getByText("OCT-1")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "最近活动" })).toBeInTheDocument();

  await userEvent.click(within(row).getByRole("button", { name: "关闭" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
    "/api/agents/agent-1",
    expect.objectContaining({
      method: "PATCH",
      body: JSON.stringify({ runtimeConfig: { heartbeat: { enabled: false, intervalSec: 60, wakeOnDemand: true } } }),
    }),
  ));

  await userEvent.click(within(row).getByRole("button", { name: "立即运行" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
    "/api/agents/agent-1/heartbeat/invoke",
    expect.objectContaining({ method: "POST" }),
  ));
});

it("enabling an organization heartbeat with no interval writes a default interval and avoids 0s copy", async () => {
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
        agentRuntimeConfig: { model: "openai/gpt-5" },
        runtimeConfig: { heartbeat: { enabled: false, intervalSec: 0, wakeOnDemand: true } },
        budgetMonthlyCents: 0,
        lastHeartbeatAt: null,
      }]);
    }
    if (path === "/api/orgs/org-1/heartbeat-runs" && init?.method === "GET") return respond([]);
    if (path === "/api/agents/agent-1" && init?.method === "PATCH") {
      return respond({ id: "agent-1", orgId: "org-1", name: "Builder", status: "idle" });
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/heartbeat-runs");

  const row = await screen.findByTestId("org-heartbeat-row");
  expect(within(row).getByText("每 300s")).toBeInTheDocument();
  expect(within(row).queryByText("未设置间隔")).not.toBeInTheDocument();
  expect(within(row).queryByText("每 0s")).not.toBeInTheDocument();
  expect(within(row).getByLabelText("Builder 心跳间隔秒数")).toHaveValue(300);

  await userEvent.click(within(row).getByRole("button", { name: "启用" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
    "/api/agents/agent-1",
    expect.objectContaining({
      method: "PATCH",
      body: JSON.stringify({
        runtimeConfig: { heartbeat: { enabled: true, intervalSec: 300, wakeOnDemand: true } },
      }),
    }),
  ));
});

it("updates the organization heartbeat interval inline", async () => {
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
        agentRuntimeConfig: { model: "openai/gpt-5" },
        runtimeConfig: { heartbeat: { enabled: true, intervalSec: 60, wakeOnDemand: true } },
        budgetMonthlyCents: 0,
        lastHeartbeatAt: null,
      }]);
    }
    if (path === "/api/orgs/org-1/heartbeat-runs" && init?.method === "GET") return respond([]);
    if (path === "/api/agents/agent-1" && init?.method === "PATCH") {
      return respond({ id: "agent-1", orgId: "org-1", name: "Builder", status: "idle" });
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/heartbeat-runs");

  const row = await screen.findByTestId("org-heartbeat-row");
  const interval = within(row).getByLabelText("Builder 心跳间隔秒数");
  await userEvent.clear(interval);
  await userEvent.type(interval, "180");
  await userEvent.click(within(row).getByRole("button", { name: "保存间隔" }));

  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
    "/api/agents/agent-1",
    expect.objectContaining({
      method: "PATCH",
      body: JSON.stringify({
        runtimeConfig: { heartbeat: { enabled: true, intervalSec: 180, wakeOnDemand: true } },
      }),
    }),
  ));
});

it("renders the heartbeat controls from the instance settings path", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs" && init?.method === "GET") return respond([{ id: "org-1", name: "Acme" }]);
    if (path === "/api/instance/scheduler-heartbeats" && init?.method === "GET") {
      return respond([{
        id: "agent-1",
        orgId: "org-1",
        organizationName: "Acme",
        organizationIssuePrefix: "ACME",
        agentName: "Builder",
        agentUrlKey: "builder",
        role: "engineer",
        title: "Engineer",
        status: "idle",
        agentRuntimeType: "codex_local",
        intervalSec: 60,
        heartbeatEnabled: true,
        schedulerActive: true,
        lastHeartbeatAt: null,
      }]);
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/instance/settings/heartbeats");

  expect(await screen.findByRole("heading", { name: "心跳" })).toBeInTheDocument();
  expect(await screen.findByTestId("instance-heartbeat-row")).toBeInTheDocument();
});

it("enabling an instance heartbeat with no interval writes a default interval and avoids 0s copy", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs" && init?.method === "GET") return respond([{ id: "org-1", name: "Acme" }]);
    if (path === "/api/instance/scheduler-heartbeats" && init?.method === "GET") {
      return respond([{
        id: "agent-1",
        orgId: "org-1",
        organizationName: "Acme",
        organizationIssuePrefix: "ACME",
        agentName: "Builder",
        agentUrlKey: "builder",
        role: "engineer",
        title: "Engineer",
        status: "idle",
        agentRuntimeType: "codex_local",
        intervalSec: 0,
        heartbeatEnabled: false,
        schedulerActive: false,
        lastHeartbeatAt: null,
      }]);
    }
    if (path === "/api/agents/agent-1" && init?.method === "GET") {
      return respond({
        id: "agent-1",
        orgId: "org-1",
        name: "Builder",
        status: "idle",
        runtimeConfig: { heartbeat: { enabled: false, intervalSec: 0, wakeOnDemand: true } },
      });
    }
    if (path === "/api/agents/agent-1" && init?.method === "PATCH") {
      return respond({ id: "agent-1", orgId: "org-1", name: "Builder", status: "idle" });
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/instance/settings/heartbeats");

  const row = await screen.findByTestId("instance-heartbeat-row");
  expect(within(row).getByText("每 300s")).toBeInTheDocument();
  expect(within(row).queryByText("未设置间隔")).not.toBeInTheDocument();
  expect(within(row).queryByText("每 0s")).not.toBeInTheDocument();
  expect(within(row).getByLabelText("Builder 心跳间隔秒数")).toHaveValue(300);

  await userEvent.click(within(row).getByRole("button", { name: "启用" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
    "/api/agents/agent-1",
    expect.objectContaining({
      method: "PATCH",
      body: JSON.stringify({
        runtimeConfig: { heartbeat: { enabled: true, intervalSec: 300, wakeOnDemand: true } },
      }),
    }),
  ));
});

it("updates the instance heartbeat interval inline", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs" && init?.method === "GET") return respond([{ id: "org-1", name: "Acme" }]);
    if (path === "/api/instance/scheduler-heartbeats" && init?.method === "GET") {
      return respond([{
        id: "agent-1",
        orgId: "org-1",
        organizationName: "Acme",
        organizationIssuePrefix: "ACME",
        agentName: "Builder",
        agentUrlKey: "builder",
        role: "engineer",
        title: "Engineer",
        status: "idle",
        agentRuntimeType: "codex_local",
        intervalSec: 60,
        heartbeatEnabled: true,
        schedulerActive: true,
        lastHeartbeatAt: null,
      }]);
    }
    if (path === "/api/agents/agent-1" && init?.method === "GET") {
      return respond({
        id: "agent-1",
        orgId: "org-1",
        name: "Builder",
        status: "idle",
        runtimeConfig: { heartbeat: { enabled: true, intervalSec: 60, wakeOnDemand: true } },
      });
    }
    if (path === "/api/agents/agent-1" && init?.method === "PATCH") {
      return respond({ id: "agent-1", orgId: "org-1", name: "Builder", status: "idle" });
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/instance/settings/heartbeats");

  const row = await screen.findByTestId("instance-heartbeat-row");
  const interval = within(row).getByLabelText("Builder 心跳间隔秒数");
  await userEvent.clear(interval);
  await userEvent.type(interval, "240");
  await userEvent.click(within(row).getByRole("button", { name: "保存间隔" }));

  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
    "/api/agents/agent-1",
    expect.objectContaining({
      method: "PATCH",
      body: JSON.stringify({
        runtimeConfig: { heartbeat: { enabled: true, intervalSec: 240, wakeOnDemand: true } },
      }),
    }),
  ));
});

it("shows instance heartbeat controls inside settings", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs" && init?.method === "GET") return respond([{ id: "org-1", name: "Acme" }]);
    if (path === "/api/orgs/org-1/projects" && init?.method === "GET") return respond([]);
    if (path === "/api/llm/providers" && init?.method === "GET") return respond([]);
    if (path === "/api/llm/models" && init?.method === "GET") return respond([]);
    if (path === "/api/instance/scheduler-heartbeats" && init?.method === "GET") {
      return respond([{
        id: "agent-1",
        orgId: "org-1",
        organizationName: "Acme",
        organizationIssuePrefix: "ACME",
        agentName: "Builder",
        agentUrlKey: "builder",
        role: "engineer",
        title: "Engineer",
        status: "idle",
        agentRuntimeType: "codex_local",
        intervalSec: 60,
        heartbeatEnabled: true,
        schedulerActive: true,
        lastHeartbeatAt: null,
      }]);
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/agents");
  await userEvent.click(await screen.findByRole("button", { name: "设置" }));
  const dialog = within(screen.getByRole("dialog", { name: "设置" }));

  await userEvent.click(dialog.getByRole("button", { name: /心跳/ }));
  expect(dialog.getByRole("heading", { name: "心跳" })).toBeInTheDocument();
  expect(dialog.getByLabelText("心跳设置")).toHaveClass("runtime-settings");
  expect(dialog.getByText("Scheduler")).toBeInTheDocument();
  expect(await dialog.findByTestId("instance-heartbeat-row")).toBeInTheDocument();
  expect(dialog.getByText("Builder")).toBeInTheDocument();
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
