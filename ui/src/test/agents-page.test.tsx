import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { renderApp, respond } from "./render-app";

afterEach(() => {
  cleanup();
  localStorage.clear();
  document.documentElement.lang = "";
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
    if (path === "/api/orgs/org-1/agent-hires" && init?.method === "POST") {
      return respond({ agent: { id: "agent-2", name: "Reviewer", role: "qa", status: "idle" }, approval: null }, 201);
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
  await userEvent.click(screen.getByRole("button", { name: "组织菜单" }));
  const organizationMenu = within(screen.getByRole("navigation", { name: "组织切换菜单" }));
  expect(organizationMenu.getByRole("link", { name: "组织设置" })).toHaveAttribute(
    "href",
    "/orgs/org-1/settings",
  );
  expect(organizationMenu.getByRole("link", { name: "创建组织" })).toHaveAttribute("href", "/organizations");
  expect(
    organizationMenu.getByRole("link", { name: /设计团队/ }),
  ).toHaveAttribute("href", "/orgs/org-2/agents");

  await userEvent.click(primaryNavigation.getByRole("button", { name: "快速创建" }));
  await userEvent.click(screen.getByRole("button", { name: "创建智能体" }));
  await userEvent.click(await screen.findByRole("button", { name: "使用名称建议" }));
  expect(screen.getByLabelText(/智能体名称/)).toHaveValue("Suggested Agent");
  await userEvent.clear(screen.getByLabelText(/智能体名称/));
  await userEvent.type(await screen.findByLabelText(/智能体名称/), "Reviewer");
  await userEvent.selectOptions(screen.getByLabelText("角色"), "qa");
  await userEvent.selectOptions(screen.getByLabelText("角色"), "cto");
  expect(within(screen.getByLabelText("Runtime")).queryByRole("option", { name: "hermes_local" })).not.toBeInTheDocument();
  expect(within(screen.getByLabelText("Runtime")).queryByRole("option", { name: "gemini_local" })).not.toBeInTheDocument();
  expect(within(screen.getByLabelText("Runtime")).queryByRole("option", { name: "cursor" })).not.toBeInTheDocument();
  expect(within(screen.getByLabelText("Runtime")).queryByRole("option", { name: "pi_local" })).not.toBeInTheDocument();
  await userEvent.selectOptions(screen.getByLabelText("Runtime"), "http");
  await userEvent.type(screen.getByLabelText("标题"), "Runtime owner");
  await userEvent.type(screen.getByLabelText("能力说明"), "Own runtime rollout");
  await userEvent.type(screen.getByLabelText("月度预算（美元）"), "50");
  await userEvent.click(screen.getByRole("button", { name: "个性化配置" }));
  fireEvent.change(screen.getByLabelText("Agent runtime config"), { target: { value: '{"model":"provider/model"}' } });
  fireEvent.change(screen.getByLabelText("Metadata"), { target: { value: '{"team":"runtime"}' } });
  await userEvent.type(screen.getByLabelText("期望技能"), "review,debug");
  await userEvent.click(screen.getByRole("button", { name: "新建智能体" }));

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/agent-hires",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        name: "Reviewer",
        role: "cto",
        title: "Runtime owner",
        capabilities: "Own runtime rollout",
        agentRuntimeType: "http",
        agentRuntimeConfig: { model: "provider/model" },
        budgetMonthlyCents: 5000,
        metadata: { team: "runtime" },
        desiredSkills: ["review", "debug"],
      }),
    }),
  );
}, 10000);

it("creates the first agent as the organization CEO", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-empty/agents" && init?.method === "GET") {
      return respond([]);
    }
    if (path === "/api/orgs/org-empty/agents/name-suggestion" && init?.method === "GET") {
      return respond({ name: "Founder" });
    }
    if (path === "/api/orgs/org-empty/agent-hires" && init?.method === "POST") {
      return respond({ agent: { id: "agent-ceo", name: "Founder", role: "ceo", status: "idle" }, approval: null }, 201);
    }
    return respond({ id: "agent-ceo", name: "Founder", role: "ceo", status: "idle" }, 201);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-empty/agents/new");
  expect(await screen.findByText("首个智能体将作为 CEO 创建")).toBeInTheDocument();
  expect(screen.getByLabelText("角色")).toBeDisabled();

  await userEvent.type(screen.getByLabelText("智能体名称"), "Founder");
  await userEvent.selectOptions(screen.getByLabelText("Runtime"), "codex_local");
  await userEvent.type(await screen.findByLabelText("模型配置"), "openai/gpt-5");
  await userEvent.click(screen.getByRole("button", { name: "创建 CEO" }));

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-empty/agent-hires",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        name: "Founder",
        role: "ceo",
        agentRuntimeType: "codex_local",
        agentRuntimeConfig: { model: "openai/gpt-5" },
      }),
    }),
  );
}, 10000);

it("lets the server name a hired agent when the name is blank", async () => {
  const existingAgent = { id: "agent-ceo", orgId: "org-1", name: "CEO", role: "ceo", status: "idle" };
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1" && init?.method === "GET") {
      return respond({ id: "org-1", urlKey: "core", name: "核心团队", status: "active", requireBoardApprovalForNewAgents: false });
    }
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") return respond([existingAgent]);
    if (path === "/api/orgs/org-1/agents/name-suggestion" && init?.method === "GET") return respond({ name: "engineer-1" });
    if (path === "/api/orgs/org-1/agent-hires" && init?.method === "POST") {
      return respond({ agent: { id: "agent-2", name: "qa-1", role: "qa", status: "idle" }, approval: null }, 201);
    }
    return respond({ id: "agent-2", name: "qa-1", role: "qa", status: "idle" }, 201);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/agents/new");
  expect(await screen.findByText("名称可不填；server 会按角色自动生成，例如 engineer-1，并设置汇报关系。")).toBeInTheDocument();
  await userEvent.selectOptions(screen.getByLabelText("角色"), "qa");
  await userEvent.click(screen.getByRole("button", { name: "新建智能体" }));

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/agent-hires",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        role: "qa",
        agentRuntimeType: "process",
        agentRuntimeConfig: {},
      }),
    }),
  );
}, 10000);

it("requires provider/model when creating a model-provider runtime agent", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([{ id: "agent-1", orgId: "org-1", name: "Builder", role: "engineer", status: "idle" }]);
    }
    if (path === "/api/orgs/org-1/agents/name-suggestion" && init?.method === "GET") {
      return respond({ name: "Suggested Agent" });
    }
    if (path === "/api/llm/providers" && init?.method === "GET") {
      return respond([{ providerId: "deepseek", name: "DeepSeek", runtimeType: "opencode_local", enabled: true }]);
    }
    if (path === "/api/llm/providers/deepseek/models" && init?.method === "GET") {
      return respond([{ providerId: "deepseek", modelId: "deepseek-v4-flash", displayName: "deepseek-v4-flash (local)", enabled: true }]);
    }
    if (path === "/api/orgs/org-1/agent-hires" && init?.method === "POST") {
      return respond({ agent: { id: "agent-2", name: "OpenCode Agent", role: "engineer", status: "idle" }, approval: null }, 201);
    }
    return respond({ id: "agent-2", name: "OpenCode Agent", role: "engineer", status: "idle" }, 201);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/agents/new");
  await userEvent.type(await screen.findByLabelText(/智能体名称/), "OpenCode Agent");
  await userEvent.selectOptions(screen.getByLabelText("Runtime"), "opencode_local");
  await userEvent.click(screen.getByRole("button", { name: "新建智能体" }));
  expect(screen.getByText("模型必须使用 provider/model 格式，例如 openai/gpt-5。")).toBeInTheDocument();
  expect(fetchMock).not.toHaveBeenCalledWith(
    "/api/orgs/org-1/agent-hires",
    expect.objectContaining({ method: "POST" }),
  );

  await userEvent.selectOptions(await screen.findByLabelText("模型配置"), "deepseek/deepseek-v4-flash");
  await userEvent.click(screen.getByRole("button", { name: "新建智能体" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/agent-hires",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        name: "OpenCode Agent",
        role: "engineer",
        agentRuntimeType: "opencode_local",
        agentRuntimeConfig: { model: "deepseek/deepseek-v4-flash" },
      }),
    }),
  );
}, 10000);

it("builds openclaw gateway config from dedicated runtime fields", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([{ id: "agent-1", orgId: "org-1", name: "CEO", role: "ceo", status: "idle" }]);
    }
    if (path === "/api/orgs/org-1/agents/name-suggestion" && init?.method === "GET") {
      return respond({ name: "openclaw-1" });
    }
    if (path === "/api/orgs/org-1/agent-hires" && init?.method === "POST") {
      return respond({ agent: { id: "agent-2", name: "OpenClaw Agent", role: "engineer", status: "idle" }, approval: null }, 201);
    }
    return respond({ id: "agent-2", name: "OpenClaw Agent", role: "engineer", status: "idle" }, 201);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/agents/new");
  await userEvent.type(await screen.findByLabelText(/智能体名称/), "OpenClaw Agent");
  await userEvent.selectOptions(screen.getByLabelText("Runtime"), "openclaw_gateway");
  expect(screen.getByText("使用推荐默认配置")).toBeInTheDocument();
  expect(screen.queryByLabelText("Gateway URL")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "个性化配置" }));
  await userEvent.type(await screen.findByLabelText("Gateway URL"), "wss://gateway.example/ws");
  await userEvent.type(screen.getByLabelText("Auth token"), "secret-token");
  await userEvent.selectOptions(screen.getByLabelText("Session key strategy"), "issue");
  await userEvent.click(screen.getByRole("button", { name: "新建智能体" }));

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/agent-hires",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        name: "OpenClaw Agent",
        role: "engineer",
        agentRuntimeType: "openclaw_gateway",
        agentRuntimeConfig: {
          url: "wss://gateway.example/ws",
          authToken: "secret-token",
          sessionKeyStrategy: "issue",
        },
      }),
    }),
  );
}, 10000);

it("hires agents as the CEO actor and opens the pending approval agent", async () => {
  const ceo = { id: "agent-ceo", orgId: "org-1", name: "CEO", role: "ceo", status: "idle", agentRuntimeType: "process", agentRuntimeConfig: {}, runtimeConfig: {}, budgetMonthlyCents: 0 };
  const pendingAgent = { id: "agent-pending", orgId: "org-1", name: "Reviewer", role: "qa", status: "pending_approval", agentRuntimeType: "process", agentRuntimeConfig: {}, runtimeConfig: {}, budgetMonthlyCents: 0 };
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1" && init?.method === "GET") {
      return respond({ id: "org-1", urlKey: "core", name: "核心团队", status: "active", requireBoardApprovalForNewAgents: true });
    }
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([ceo]);
    }
    if (path === "/api/orgs/org-1/agents/name-suggestion" && init?.method === "GET") {
      return respond({ name: "Suggested Agent" });
    }
    if (path === "/api/orgs/org-1/agent-hires" && init?.method === "POST") {
      return respond({
        agent: pendingAgent,
        approval: { id: "approval-1", orgId: "org-1", type: "hire_agent", status: "pending" },
      }, 201);
    }
    if (path === "/api/agents/agent-pending" && init?.method === "GET") return respond(pendingAgent);
    if (path === "/api/agents/agent-pending/runtime-state" && init?.method === "GET") {
      return respond({ lastRunStatus: null, sessionDisplayId: null, totalInputTokens: 0, totalOutputTokens: 0, totalCostCents: 0 });
    }
    if (path === "/api/orgs/org-1/heartbeat-runs?agentId=agent-pending" && init?.method === "GET") return respond([]);
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/agents/new");
  expect(await screen.findByText("当前组织要求审批。创建后智能体将显示为待审批，审批通过后才可用。")).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText(/智能体名称/), "Reviewer");
  await userEvent.selectOptions(screen.getByLabelText("角色"), "qa");
  await userEvent.click(screen.getByRole("button", { name: "新建智能体" }));

  const hireCall = fetchMock.mock.calls.find(([path, init]) => path === "/api/orgs/org-1/agent-hires" && init?.method === "POST");
  expect(hireCall).toBeTruthy();
  const headers = hireCall?.[1]?.headers as Headers;
  expect(headers.get("x-test-agent-id")).toBe("agent-ceo");
  expect(headers.get("x-test-org-id")).toBe("org-1");
  expect(await screen.findByRole("heading", { name: "Reviewer" })).toBeInTheDocument();
  expect(screen.getByText("待审批")).toBeInTheDocument();
}, 10000);

it("shows a permission error when the actor cannot hire agents", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1" && init?.method === "GET") {
      return respond({ id: "org-1", urlKey: "core", name: "核心团队", status: "active", requireBoardApprovalForNewAgents: false });
    }
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([{ id: "agent-1", orgId: "org-1", name: "Builder", role: "engineer", status: "idle" }]);
    }
    if (path === "/api/orgs/org-1/agents/name-suggestion" && init?.method === "GET") {
      return respond({ name: "Suggested Agent" });
    }
    if (path === "/api/orgs/org-1/agent-hires" && init?.method === "POST") {
      return respond({ detail: "Agent does not have permission to create agents" }, 403);
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/agents/new");
  expect(await screen.findByText("当前组织不要求审批。创建成功后智能体可直接使用。")).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText(/智能体名称/), "Reviewer");
  await userEvent.click(screen.getByRole("button", { name: "新建智能体" }));

  expect(await screen.findByText("无创建智能体权限")).toBeInTheDocument();
}, 10000);

it("manages runtime providers and models from settings", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs" && init?.method === "GET") {
      return respond([{ id: "org-1", urlKey: "core", name: "核心团队", status: "active" }]);
    }
    if (path === "/api/health" && init?.method === "GET") {
      return respond({
        status: "ok",
        storage: {
          provider: "minio",
          bucket: "octopus",
          endpoint: "http://127.0.0.1:9000",
          pathStyle: true,
        },
      });
    }
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([]);
    }
    if (path === "/api/llm/providers" && init?.method === "GET") {
      return respond([
        { scope: "instance", providerId: "kimi", name: "Kimi", runtimeType: "opencode_local", protocol: "openai_chat_completions", baseUrl: "https://api.moonshot.cn/v1", enabled: true, hasApiKey: true },
        { scope: "instance", providerId: "openrouter", name: "OpenRouter", runtimeType: "opencode_local", protocol: "openai_chat_completions", baseUrl: "https://openrouter.ai/api/v1", enabled: true, hasApiKey: false },
      ]);
    }
    if (path === "/api/llm/providers" && init?.method === "GET") {
      return respond([{ providerId: "openai", name: "OpenAI", runtimeType: "codex_local", enabled: true, hasApiKey: true }]);
    }
    if (path === "/api/llm/providers/kimi/models" && init?.method === "GET") {
      return respond([{ scope: "instance", modelId: "kimi/kimi-k2.5", displayName: "Kimi K2.5", metadata: { pricing: { inputCostPer1M: 0.12, outputCostPer1M: 0.24 } }, enabled: true }]);
    }
    if (path === "/api/llm/providers/openrouter/models" && init?.method === "GET") {
      return respond([{ scope: "instance", modelId: "openai/gpt-5", displayName: "GPT-5", enabled: true }]);
    }
    if (path === "/api/llm/providers" && init?.method === "POST") {
      return respond({ providerId: "openrouter", name: "OpenRouter", runtimeType: "opencode_local" }, 201);
    }
    if (path === "/api/llm/providers/kimi" && init?.method === "PATCH") {
      return respond({ providerId: "kimi", name: "Kimi Updated", runtimeType: "opencode_local" });
    }
    if (path === "/api/llm/providers/kimi/models" && init?.method === "POST") {
      return respond({ modelId: "kimi/kimi-k3", displayName: "Kimi K3" }, 201);
    }
    if (path === "/api/llm/providers/kimi/models/kimi%2Fkimi-k2.5" && init?.method === "PATCH") {
      return respond({ modelId: "kimi/kimi-k2.5", displayName: "Kimi K2.5 Updated" });
    }
    if (path === "/api/llm/providers/kimi/models/kimi%2Fkimi-k2.5" && init?.method === "DELETE") {
      return respond({ modelId: "kimi/kimi-k2.5", displayName: "Kimi K2.5" });
    }
    if (path === "/api/llm/providers/openrouter" && init?.method === "DELETE") {
      return respond({ providerId: "openrouter", name: "OpenRouter", runtimeType: "opencode_local" });
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("confirm", vi.fn(() => true));

  renderApp("/orgs/org-1/agents");
  await userEvent.click(await screen.findByRole("button", { name: "设置" }));
  const dialog = within(screen.getByRole("dialog", { name: "设置" }));

  expect(dialog.getByRole("button", { name: /供应商/ })).toHaveClass("active");
  expect(dialog.queryByRole("button", { name: /成本/ })).not.toBeInTheDocument();
  expect(dialog.getByRole("button", { name: /存储/ })).toBeInTheDocument();
  expect(dialog.getByRole("button", { name: /通用/ })).toBeInTheDocument();
  expect(dialog.getByRole("button", { name: /关于/ })).toBeInTheDocument();
  await userEvent.click(dialog.getByRole("button", { name: /存储/ }));
  expect(dialog.getByRole("heading", { name: "存储" })).toBeInTheDocument();
  expect(dialog.getByText("minio")).toBeInTheDocument();
  expect(dialog.getByText("octopus")).toBeInTheDocument();
  expect(dialog.getByText("http://127.0.0.1:9000")).toBeInTheDocument();
  await userEvent.click(dialog.getByRole("button", { name: /通用/ }));
  expect(dialog.getByRole("heading", { name: "通用" })).toBeInTheDocument();
  expect(dialog.getByRole("button", { name: "简体中文" })).toHaveClass("active");
  await userEvent.click(dialog.getByRole("button", { name: "English" }));
  expect(window.localStorage.getItem("octopus.locale")).toBe("en-US");
  expect(document.documentElement.lang).toBe("en-US");

  await userEvent.click(dialog.getByRole("button", { name: /供应商/ }));
  expect(await dialog.findByRole("heading", { name: "Runtime Providers" })).toBeInTheDocument();
  const englishKimiProvider = within(await dialog.findByRole("article", { name: "Kimi provider" }));
  expect(englishKimiProvider.queryByRole("button", { name: "编辑" })).not.toBeInTheDocument();
  expect(englishKimiProvider.queryByRole("button", { name: "Edit" })).toBeInTheDocument();

  await userEvent.click(dialog.getByRole("button", { name: /通用/ }));
  await userEvent.click(dialog.getByRole("button", { name: "简体中文" }));
  expect(window.localStorage.getItem("octopus.locale")).toBe("zh-CN");
  expect(document.documentElement.lang).toBe("zh-CN");

  await userEvent.click(dialog.getByRole("button", { name: /供应商/ }));
  expect(await dialog.findByRole("heading", { name: "模型供应商" })).toBeInTheDocument();
  expect(dialog.queryByLabelText("运行时")).not.toBeInTheDocument();
  const kimiProvider = within(await dialog.findByRole("article", { name: "Kimi provider" }));
  const openrouterProvider = within(await dialog.findByRole("article", { name: "OpenRouter provider" }));
  expect(kimiProvider.getByText("Kimi K2.5")).toBeInTheDocument();
  expect(kimiProvider.getByText("价格：输入 $0.12 / 输出 $0.24 每 100 万 tokens")).toBeInTheDocument();
  expect(kimiProvider.getAllByText("Instance").length).toBeGreaterThanOrEqual(2);
  expect(openrouterProvider.getByText("GPT-5")).toBeInTheDocument();
  expect(openrouterProvider.getAllByText("Instance").length).toBeGreaterThanOrEqual(2);
  expect(kimiProvider.queryByRole("button", { name: "新增模型" })).not.toBeInTheDocument();
  expect(kimiProvider.queryByRole("button", { name: "编辑" })).toBeInTheDocument();
  expect(kimiProvider.getByRole("button", { name: "Kimi 更多操作" })).toBeInTheDocument();
  expect(kimiProvider.getByRole("button", { name: "禁用" })).toBeInTheDocument();
  expect(kimiProvider.getByRole("button", { name: "删除" })).toBeInTheDocument();
  expect(dialog.queryByLabelText("Provider ID")).not.toBeInTheDocument();

  await userEvent.click(dialog.getByRole("button", { name: "新建 Provider" }));
  const providerDialog = within(screen.getByRole("dialog", { name: "新建 Provider" }));
  await userEvent.type(providerDialog.getByLabelText("Provider ID"), "openrouter");
  await userEvent.type(providerDialog.getByLabelText("Provider 名称"), "OpenRouter");
  await userEvent.type(providerDialog.getByLabelText("Base URL"), "https://openrouter.ai/api/v1");
  await userEvent.type(providerDialog.getByLabelText("API Key"), "sk-test");
  await userEvent.click(providerDialog.getByRole("button", { name: "保存 Provider" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/llm/providers",
    expect.objectContaining({
      method: "POST",
      body: expect.stringContaining('"providerId":"openrouter"'),
    }),
  );

  await userEvent.click(kimiProvider.getByRole("button", { name: "Kimi 更多操作" }));
  await userEvent.click(kimiProvider.getByRole("menuitem", { name: "编辑" }));
  const providerEditDialog = within(screen.getByRole("dialog", { name: "编辑 Provider" }));
  await userEvent.clear(providerEditDialog.getByLabelText("Provider 名称"));
  await userEvent.type(providerEditDialog.getByLabelText("Provider 名称"), "Kimi Updated");
  await userEvent.click(providerEditDialog.getByRole("button", { name: "保存 Provider" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/llm/providers/kimi",
    expect.objectContaining({
      method: "PATCH",
      body: expect.stringContaining('"name":"Kimi Updated"'),
    }),
  );

  await userEvent.click(kimiProvider.getByRole("button", { name: "Kimi 更多操作" }));
  await userEvent.click(kimiProvider.getByRole("menuitem", { name: "禁用" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/llm/providers/kimi",
    expect.objectContaining({
      method: "PATCH",
      body: expect.stringContaining('"enabled":false'),
    }),
  );

  await userEvent.click(kimiProvider.getByRole("button", { name: "Kimi 更多操作" }));
  await userEvent.click(kimiProvider.getByRole("menuitem", { name: "新增模型" }));
  const modelDialog = within(screen.getByRole("dialog", { name: "新建 Model" }));
  await userEvent.type(modelDialog.getByLabelText("Model ID"), "kimi/kimi-k3");
  await userEvent.type(modelDialog.getByLabelText("模型显示名称"), "Kimi K3");
  await userEvent.click(modelDialog.getByRole("button", { name: "保存 Model" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/llm/providers/kimi/models",
    expect.objectContaining({
      method: "POST",
      body: expect.stringContaining('"modelId":"kimi/kimi-k3"'),
    }),
  );

  await userEvent.click(kimiProvider.getByRole("button", { name: "编辑" }));
  const modelEditDialog = within(screen.getByRole("dialog", { name: "编辑 Model" }));
  expect(modelEditDialog.getByLabelText("输入 / 100 万 tokens")).toHaveValue(0.12);
  expect(modelEditDialog.getByLabelText("输出 / 100 万 tokens")).toHaveValue(0.24);
  await userEvent.clear(modelEditDialog.getByLabelText("模型显示名称"));
  await userEvent.type(modelEditDialog.getByLabelText("模型显示名称"), "Kimi K2.5 Updated");
  await userEvent.clear(modelEditDialog.getByLabelText("输入 / 100 万 tokens"));
  await userEvent.type(modelEditDialog.getByLabelText("输入 / 100 万 tokens"), "0.14");
  await userEvent.clear(modelEditDialog.getByLabelText("输出 / 100 万 tokens"));
  await userEvent.type(modelEditDialog.getByLabelText("输出 / 100 万 tokens"), "0.28");
  await userEvent.click(modelEditDialog.getByRole("button", { name: "保存 Model" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/llm/providers/kimi/models/kimi%2Fkimi-k2.5",
    expect.objectContaining({
      method: "PATCH",
      body: expect.stringContaining('"displayName":"Kimi K2.5 Updated"'),
    }),
  );
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/llm/providers/kimi/models/kimi%2Fkimi-k2.5",
    expect.objectContaining({
      method: "PATCH",
      body: expect.stringContaining('"pricing":{"inputCostPer1M":0.14,"outputCostPer1M":0.28}'),
    }),
  );

  await userEvent.click(kimiProvider.getByRole("button", { name: "禁用" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/llm/providers/kimi/models/kimi%2Fkimi-k2.5",
    expect.objectContaining({
      method: "PATCH",
      body: expect.stringContaining('"enabled":false'),
    }),
  );

  await userEvent.click(kimiProvider.getByRole("button", { name: "删除" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/llm/providers/kimi/models/kimi%2Fkimi-k2.5",
    expect.objectContaining({ method: "DELETE" }),
  );

  await userEvent.click(openrouterProvider.getByRole("button", { name: "OpenRouter 更多操作" }));
  await userEvent.click(openrouterProvider.getByRole("menuitem", { name: "删除" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/llm/providers/openrouter",
    expect.objectContaining({ method: "DELETE" }),
  );

}, 10000);

it("manages runtime providers and models from settings", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs" && init?.method === "GET") {
      return respond([{ id: "org-1", urlKey: "core", name: "核心团队", status: "active" }]);
    }
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([]);
    }
    if (path === "/api/llm/providers" && init?.method === "GET") {
      return respond([
        { providerId: "kimi", name: "Kimi", runtimeType: "opencode_local", protocol: "openai_chat_completions", baseUrl: "https://api.moonshot.cn/v1", enabled: true, hasApiKey: true },
        { providerId: "openrouter", name: "OpenRouter", runtimeType: "opencode_local", protocol: "openai_chat_completions", baseUrl: "https://openrouter.ai/api/v1", enabled: true, hasApiKey: false },
      ]);
    }
    if (path === "/api/llm/providers" && init?.method === "GET") {
      return respond([{ providerId: "openai", name: "OpenAI", runtimeType: "codex_local", enabled: true, hasApiKey: true }]);
    }
    if (path === "/api/llm/providers/kimi/models" && init?.method === "GET") {
      return respond([{ modelId: "kimi/kimi-k2.5", displayName: "Kimi K2.5", enabled: true }]);
    }
    if (path === "/api/llm/providers/openrouter/models" && init?.method === "GET") {
      return respond([{ modelId: "openai/gpt-5", displayName: "GPT-5", enabled: true }]);
    }
    if (path === "/api/llm/providers" && init?.method === "POST") {
      return respond({ providerId: "openrouter", name: "OpenRouter", runtimeType: "opencode_local" }, 201);
    }
    if (path === "/api/llm/providers/kimi" && init?.method === "PATCH") {
      return respond({ providerId: "kimi", name: "Kimi Updated", runtimeType: "opencode_local" });
    }
    if (path === "/api/llm/providers/kimi/models" && init?.method === "POST") {
      return respond({ modelId: "kimi/kimi-k3", displayName: "Kimi K3" }, 201);
    }
    if (path === "/api/llm/providers/kimi/models/kimi%2Fkimi-k2.5" && init?.method === "PATCH") {
      return respond({ modelId: "kimi/kimi-k2.5", displayName: "Kimi K2.5 Updated" });
    }
    if (path === "/api/llm/providers/kimi/models/kimi%2Fkimi-k2.5" && init?.method === "DELETE") {
      return respond({ modelId: "kimi/kimi-k2.5", displayName: "Kimi K2.5" });
    }
    if (path === "/api/llm/providers/openrouter" && init?.method === "DELETE") {
      return respond({ providerId: "openrouter", name: "OpenRouter", runtimeType: "opencode_local" });
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("confirm", vi.fn(() => true));

  renderApp("/orgs/org-1/agents");
  await userEvent.click(await screen.findByRole("button", { name: "设置" }));
  const dialog = within(screen.getByRole("dialog", { name: "设置" }));

  expect(dialog.getByRole("button", { name: /供应商/ })).toHaveClass("active");
  expect(dialog.getByRole("button", { name: /通用/ })).toBeInTheDocument();
  expect(dialog.getByRole("button", { name: /关于/ })).toBeInTheDocument();
  expect(await dialog.findByRole("heading", { name: "模型供应商" })).toBeInTheDocument();
  expect(dialog.queryByLabelText("运行时")).not.toBeInTheDocument();
  const kimiProvider = within(await dialog.findByRole("article", { name: "Kimi provider" }));
  const openrouterProvider = within(await dialog.findByRole("article", { name: "OpenRouter provider" }));
  expect(kimiProvider.getByText("Kimi K2.5")).toBeInTheDocument();
  expect(openrouterProvider.getByText("GPT-5")).toBeInTheDocument();
  expect(kimiProvider.queryByRole("button", { name: "新增模型" })).not.toBeInTheDocument();
  expect(kimiProvider.queryByRole("button", { name: "编辑" })).toBeInTheDocument();
  expect(kimiProvider.getByRole("button", { name: "Kimi 更多操作" })).toBeInTheDocument();
  expect(kimiProvider.getByRole("button", { name: "禁用" })).toBeInTheDocument();
  expect(kimiProvider.getByRole("button", { name: "删除" })).toBeInTheDocument();
  expect(dialog.queryByLabelText("Provider ID")).not.toBeInTheDocument();

  await userEvent.click(dialog.getByRole("button", { name: "新建 Provider" }));
  const providerDialog = within(screen.getByRole("dialog", { name: "新建 Provider" }));
  await userEvent.type(providerDialog.getByLabelText("Provider ID"), "openrouter");
  await userEvent.type(providerDialog.getByLabelText("Provider 名称"), "OpenRouter");
  await userEvent.type(providerDialog.getByLabelText("Base URL"), "https://openrouter.ai/api/v1");
  await userEvent.type(providerDialog.getByLabelText("API Key"), "sk-test");
  await userEvent.click(providerDialog.getByRole("button", { name: "保存 Provider" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/llm/providers",
    expect.objectContaining({
      method: "POST",
      body: expect.stringContaining('"providerId":"openrouter"'),
    }),
  );

  await userEvent.click(kimiProvider.getByRole("button", { name: "Kimi 更多操作" }));
  await userEvent.click(kimiProvider.getByRole("menuitem", { name: "编辑" }));
  const providerEditDialog = within(screen.getByRole("dialog", { name: "编辑 Provider" }));
  await userEvent.clear(providerEditDialog.getByLabelText("Provider 名称"));
  await userEvent.type(providerEditDialog.getByLabelText("Provider 名称"), "Kimi Updated");
  await userEvent.click(providerEditDialog.getByRole("button", { name: "保存 Provider" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/llm/providers/kimi",
    expect.objectContaining({
      method: "PATCH",
      body: expect.stringContaining('"name":"Kimi Updated"'),
    }),
  );

  await userEvent.click(kimiProvider.getByRole("button", { name: "Kimi 更多操作" }));
  await userEvent.click(kimiProvider.getByRole("menuitem", { name: "禁用" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/llm/providers/kimi",
    expect.objectContaining({
      method: "PATCH",
      body: expect.stringContaining('"enabled":false'),
    }),
  );

  await userEvent.click(kimiProvider.getByRole("button", { name: "Kimi 更多操作" }));
  await userEvent.click(kimiProvider.getByRole("menuitem", { name: "新增模型" }));
  const modelDialog = within(screen.getByRole("dialog", { name: "新建 Model" }));
  await userEvent.type(modelDialog.getByLabelText("Model ID"), "kimi/kimi-k3");
  await userEvent.type(modelDialog.getByLabelText("模型显示名称"), "Kimi K3");
  await userEvent.click(modelDialog.getByRole("button", { name: "保存 Model" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/llm/providers/kimi/models",
    expect.objectContaining({
      method: "POST",
      body: expect.stringContaining('"modelId":"kimi/kimi-k3"'),
    }),
  );

  await userEvent.click(kimiProvider.getByRole("button", { name: "编辑" }));
  const modelEditDialog = within(screen.getByRole("dialog", { name: "编辑 Model" }));
  await userEvent.clear(modelEditDialog.getByLabelText("模型显示名称"));
  await userEvent.type(modelEditDialog.getByLabelText("模型显示名称"), "Kimi K2.5 Updated");
  await userEvent.click(modelEditDialog.getByRole("button", { name: "保存 Model" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/llm/providers/kimi/models/kimi%2Fkimi-k2.5",
    expect.objectContaining({
      method: "PATCH",
      body: expect.stringContaining('"displayName":"Kimi K2.5 Updated"'),
    }),
  );

  await userEvent.click(kimiProvider.getByRole("button", { name: "禁用" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/llm/providers/kimi/models/kimi%2Fkimi-k2.5",
    expect.objectContaining({
      method: "PATCH",
      body: expect.stringContaining('"enabled":false'),
    }),
  );

  await userEvent.click(kimiProvider.getByRole("button", { name: "删除" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/llm/providers/kimi/models/kimi%2Fkimi-k2.5",
    expect.objectContaining({ method: "DELETE" }),
  );

  await userEvent.click(openrouterProvider.getByRole("button", { name: "OpenRouter 更多操作" }));
  await userEvent.click(openrouterProvider.getByRole("menuitem", { name: "删除" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/llm/providers/openrouter",
    expect.objectContaining({ method: "DELETE" }),
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
