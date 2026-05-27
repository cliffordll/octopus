import { cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { renderApp, respond } from "./render-app";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("opens the first agent by default and creates one from the new agent flow", async () => {
  const agent = { id: "agent-1", orgId: "org-1", name: "Builder", role: "engineer", status: "idle", agentRuntimeType: "process", agentRuntimeConfig: {}, runtimeConfig: {}, budgetMonthlyCents: 0 };
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs" && init?.method === "GET") {
      return respond([
        { id: "org-1", urlKey: "core", name: "核心团队", status: "active" },
        { id: "org-2", urlKey: "design", name: "设计团队", status: "active" },
      ]);
    }
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([agent]);
    }
    if (path === "/api/agents/agent-1" && init?.method === "GET") {
      return respond(agent);
    }
    if (path === "/api/agents/agent-1/runtime-state" && init?.method === "GET") {
      return respond({ lastRunStatus: null, sessionDisplayId: null, totalInputTokens: 0, totalOutputTokens: 0, totalCostCents: 0 });
    }
    return respond({ id: "agent-2", name: "Reviewer", role: "qa", status: "idle" }, 201);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/agents");
  expect(await screen.findByRole("heading", { name: "Builder" })).toBeInTheDocument();
  expect(screen.getByRole("navigation", { name: "智能体详情导航" })).toBeInTheDocument();
  expect(screen.queryByLabelText("状态筛选")).not.toBeInTheDocument();
  const primaryNavigation = within(screen.getByRole("navigation", { name: "主导航" }));
  expect(primaryNavigation.getByRole("link", { name: "消息" })).toHaveAttribute("href", "/orgs/org-1/chats");
  expect(primaryNavigation.getByRole("link", { name: "任务" })).toHaveAttribute("href", "/orgs/org-1/issues");
  expect(primaryNavigation.getByRole("link", { name: "智能体" })).toHaveAttribute("href", "/orgs/org-1/agents");
  expect(primaryNavigation.getByRole("link", { name: "组织" })).toHaveAttribute("href", "/organizations");
  expect(screen.queryByRole("navigation", { name: "组织导航" })).not.toBeInTheDocument();
  expect(
    within(screen.getByRole("navigation", { name: "智能体导航" })).getByRole("link", { name: /Builder/ }),
  ).toHaveAttribute("href", "/orgs/org-1/agents/agent-1");
  await userEvent.click(screen.getByRole("button", { name: "切换组织" }));
  expect(
    within(screen.getByRole("navigation", { name: "组织切换菜单" })).getByRole("link", {
      name: /设计团队/,
    }),
  ).toHaveAttribute("href", "/orgs/org-2/agents");

  await userEvent.click(
    within(screen.getByRole("navigation", { name: "智能体导航" })).getByRole("link", { name: /新建智能体/ }),
  );
  await userEvent.type(await screen.findByLabelText("智能体名称"), "Reviewer");
  await userEvent.selectOptions(screen.getByLabelText("角色"), "qa");
  await userEvent.selectOptions(screen.getByLabelText("Runtime"), "codex_local");
  await userEvent.click(screen.getByRole("button", { name: "新建智能体" }));

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/agents",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        name: "Reviewer",
        role: "qa",
        agentRuntimeType: "codex_local",
        agentRuntimeConfig: {},
      }),
    }),
  );
});

it("creates the first agent as the organization CEO", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-empty/agents" && init?.method === "GET") {
      return respond([]);
    }
    return respond({ id: "agent-ceo", name: "Founder", role: "ceo", status: "idle" }, 201);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-empty/agents/new");
  expect(await screen.findByText("首个智能体将作为 CEO 创建")).toBeInTheDocument();
  expect(screen.getByLabelText("角色")).toBeDisabled();

  await userEvent.type(screen.getByLabelText("智能体名称"), "Founder");
  await userEvent.selectOptions(screen.getByLabelText("Runtime"), "codex_local");
  await userEvent.click(screen.getByRole("button", { name: "创建 CEO" }));

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-empty/agents",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        name: "Founder",
        role: "ceo",
        agentRuntimeType: "codex_local",
        agentRuntimeConfig: {},
      }),
    }),
  );
});

it("shows empty detail tabs when the organization has no agents", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-empty/agents" && init?.method === "GET") {
      return respond([]);
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-empty/agents");
  const details = await screen.findByRole("navigation", { name: "智能体详情导航" });
  expect(within(details).getByRole("button", { name: "概览" })).toBeInTheDocument();
  expect(within(details).getByRole("button", { name: "配置" })).toBeInTheDocument();
  expect(within(details).getByRole("button", { name: "运行" })).toBeInTheDocument();
  expect(screen.queryByLabelText("状态筛选")).not.toBeInTheDocument();

  await userEvent.click(within(details).getByRole("button", { name: "配置" }));
  expect(screen.getByRole("heading", { name: "配置" })).toBeInTheDocument();
  expect(screen.getByText("暂无智能体。创建智能体后可查看和管理此内容。")).toBeInTheDocument();
});
