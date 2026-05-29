import { cleanup, fireEvent, screen, within } from "@testing-library/react";
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
    if (path === "/api/orgs/org-1/agents/name-suggestion" && init?.method === "GET") {
      return respond({ name: "Suggested Agent" });
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
  expect(primaryNavigation.getAllByRole("link").map((link) => link.getAttribute("href"))).toEqual([
    "/orgs/org-1/chats",
    "/orgs/org-1/agents",
    "/orgs/org-1/issues",
    "/orgs/org-1/structure",
  ]);
  expect(primaryNavigation.getByRole("link", { name: "消息" })).toHaveAttribute("href", "/orgs/org-1/chats");
  expect(primaryNavigation.getByRole("link", { name: "任务" })).toHaveAttribute("href", "/orgs/org-1/issues");
  expect(primaryNavigation.getByRole("link", { name: "智能体" })).toHaveAttribute("href", "/orgs/org-1/agents");
  expect(primaryNavigation.getByRole("link", { name: "组织" })).toHaveAttribute("href", "/orgs/org-1/structure");
  expect(screen.queryByRole("navigation", { name: "组织导航" })).not.toBeInTheDocument();
  const agentNavigation = within(screen.getByRole("navigation", { name: "智能体导航" }));
  expect(agentNavigation.getByRole("heading", { name: "团队" })).toBeInTheDocument();
  expect(agentNavigation.queryByRole("link", { name: /新建智能体/ })).not.toBeInTheDocument();
  expect(
    agentNavigation.getByRole("link", { name: /Builder/ }),
  ).toHaveAttribute("href", "/orgs/org-1/agents/agent-1");
  await userEvent.click(screen.getByRole("button", { name: "切换组织" }));
  const organizationMenu = within(screen.getByRole("navigation", { name: "组织切换菜单" }));
  expect(organizationMenu.getByRole("link", { name: "组织设置" })).toHaveAttribute(
    "href",
    "/orgs/org-1/settings",
  );
  expect(organizationMenu.getByRole("link", { name: "管理组织" })).toHaveAttribute("href", "/organizations");
  expect(
    organizationMenu.getByRole("link", { name: /设计团队/ }),
  ).toHaveAttribute("href", "/orgs/org-2/agents");

  await userEvent.click(primaryNavigation.getByRole("button", { name: "快速创建" }));
  await userEvent.click(screen.getByRole("button", { name: "创建智能体" }));
  await userEvent.click(await screen.findByRole("button", { name: "使用名称建议" }));
  expect(screen.getByLabelText("智能体名称")).toHaveValue("Suggested Agent");
  await userEvent.clear(screen.getByLabelText("智能体名称"));
  await userEvent.type(await screen.findByLabelText("智能体名称"), "Reviewer");
  await userEvent.selectOptions(screen.getByLabelText("角色"), "qa");
  await userEvent.selectOptions(screen.getByLabelText("角色"), "cto");
  await userEvent.selectOptions(screen.getByLabelText("Runtime"), "hermes_local");
  await userEvent.type(screen.getByLabelText("标题"), "Runtime owner");
  await userEvent.type(screen.getByLabelText("能力说明"), "Own runtime rollout");
  await userEvent.type(screen.getByLabelText("月度预算（cents）"), "5000");
  fireEvent.change(screen.getByLabelText("Agent runtime config"), { target: { value: '{"model":"provider/model"}' } });
  fireEvent.change(screen.getByLabelText("Metadata"), { target: { value: '{"team":"runtime"}' } });
  await userEvent.type(screen.getByLabelText("Desired Skills"), "review,debug");
  await userEvent.click(screen.getByRole("button", { name: "新建智能体" }));

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/agents",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        name: "Reviewer",
        role: "cto",
        title: "Runtime owner",
        capabilities: "Own runtime rollout",
        agentRuntimeType: "hermes_local",
        agentRuntimeConfig: { model: "provider/model" },
        budgetMonthlyCents: 5000,
        metadata: { team: "runtime" },
        desiredSkills: ["review", "debug"],
      }),
    }),
  );
});

it("creates the first agent as the organization CEO", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-empty/agents" && init?.method === "GET") {
      return respond([]);
    }
    if (path === "/api/orgs/org-empty/agents/name-suggestion" && init?.method === "GET") {
      return respond({ name: "Founder" });
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

it("requires provider/model when creating an opencode local agent", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([{ id: "agent-1", orgId: "org-1", name: "Builder", role: "engineer", status: "idle" }]);
    }
    if (path === "/api/orgs/org-1/agents/name-suggestion" && init?.method === "GET") {
      return respond({ name: "Suggested Agent" });
    }
    return respond({ id: "agent-2", name: "OpenCode Agent", role: "engineer", status: "idle" }, 201);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/agents/new");
  await userEvent.type(await screen.findByLabelText("智能体名称"), "OpenCode Agent");
  await userEvent.selectOptions(screen.getByLabelText("Runtime"), "opencode_local");
  await userEvent.click(screen.getByRole("button", { name: "新建智能体" }));
  expect(screen.getByText("OpenCode model 必须使用 provider/model 格式，例如 openai/gpt-5。")).toBeInTheDocument();
  expect(fetchMock).not.toHaveBeenCalledWith(
    "/api/orgs/org-1/agents",
    expect.objectContaining({ method: "POST" }),
  );

  await userEvent.type(screen.getByLabelText("OpenCode model"), "openai/gpt-5");
  await userEvent.click(screen.getByRole("button", { name: "新建智能体" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/agents",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        name: "OpenCode Agent",
        role: "engineer",
        agentRuntimeType: "opencode_local",
        agentRuntimeConfig: { model: "openai/gpt-5" },
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
