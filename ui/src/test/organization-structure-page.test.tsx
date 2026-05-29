import { cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { renderApp, respond } from "./render-app";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("shows current reporting relationships in the organization structure", async () => {
  const agents = [
    { id: "agent-ceo", name: "Founder", role: "ceo", status: "idle", reportsTo: null },
    { id: "agent-1", name: "Builder", role: "engineer", status: "active", reportsTo: "agent-ceo" },
  ];
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs" && init?.method === "GET") {
      return respond([{ id: "org-1", name: "核心团队", status: "active" }]);
    }
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") return respond(agents);
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/structure");

  expect(await screen.findByRole("heading", { name: "组织架构" })).toBeInTheDocument();
  expect(within(screen.getByRole("navigation", { name: "组织导航" })).getByRole("link", { name: "工作区" }))
    .toHaveAttribute("href", "/orgs/org-1/workspaces");
  expect(await screen.findByText("Builder")).toBeInTheDocument();
  expect(await screen.findByText("向 Founder 汇报")).toBeInTheDocument();
});

it("shows the organization workspace file tree and editor", async () => {
  const projects = [
    {
      id: "project-1",
      orgId: "org-1",
      name: "控制台",
      status: "planned",
      urlKey: "console",
      executionWorkspacePolicy: { enabled: true, defaultMode: "shared_workspace" },
      codebase: {
        configured: true,
        repoUrl: "https://example.com/octopus.git",
        repoRef: "main",
        effectiveLocalFolder: "D:/coding/octopus",
        origin: "project_workspace",
      },
      workspaces: [
        {
          id: "workspace-1",
          name: "主工作区",
          sourceType: "git",
          cwd: "D:/coding/octopus",
          repoUrl: "https://example.com/octopus.git",
          repoRef: "main",
          visibility: "shared",
          isPrimary: true,
          sharedWorkspaceKey: "console-main",
        },
      ],
    },
  ];
  const agents = [
    {
      id: "agent-1",
      orgId: "org-1",
      name: "agent_test1",
      role: "engineer",
      status: "idle",
      agentRuntimeType: "codex_local",
      agentRuntimeConfig: { model: "gpt-5-codex" },
    },
  ];
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/projects" && init?.method === "GET") return respond(projects);
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") return respond(agents);
    if (path === "/api/orgs/org-1/agent-configurations" && init?.method === "GET") {
      return respond([{ agentId: "agent-1", agentRuntimeConfig: { model: "gpt-5-codex" }, runtimeConfig: {} }]);
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/workspaces");

  expect(await screen.findByRole("heading", { name: "工作区" })).toBeInTheDocument();
  expect(screen.getByTestId("org-workspaces-files-card")).toBeInTheDocument();
  expect(screen.getByTestId("org-workspaces-editor-card")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Files" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Editor" })).toBeInTheDocument();
  expect(screen.queryByText("Project Workspaces")).not.toBeInTheDocument();
  expect(screen.queryByRole("navigation", { name: "项目工作区" })).not.toBeInTheDocument();
  expect(screen.getByText("artifacts")).toBeInTheDocument();
  expect(screen.getByText("dist")).toBeInTheDocument();
  expect(screen.getByText("Microsoft")).toBeInTheDocument();
  expect(screen.getByText("node_mode")).toBeInTheDocument();
  expect(screen.getByText("plans")).toBeInTheDocument();
  expect(screen.getByText("skills")).toBeInTheDocument();
  expect(screen.getByText("src")).toBeInTheDocument();
  expect(screen.getByText("agents")).toBeInTheDocument();
  const fileButtons = within(screen.getByTestId("org-workspaces-files-card"))
    .getAllByRole("button")
    .map((button) => button.textContent ?? "");
  const topLevelOrder = ["agents", "artifacts", "dist", "Microsoft", "node_mode", "plans", "skills", "src"]
    .map((label) => fileButtons.findIndex((text) => text.includes(label)));
  expect(topLevelOrder.every((index) => index >= 0)).toBe(true);
  expect([...topLevelOrder].sort((left, right) => left - right)).toEqual(topLevelOrder);
  expect(screen.getByLabelText("工作区文件内容")).toHaveValue(JSON.stringify({ agents: [] }, null, 2));
  expect(screen.queryByText("已配置代码库")).not.toBeInTheDocument();
});

it("keeps the selected workspace file from the path query", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/projects" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") return respond([]);
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/workspaces?path=package-lock.json");

  expect(await screen.findByRole("heading", { name: "工作区" })).toBeInTheDocument();
  expect(screen.getAllByText("package-lock.json").length).toBeGreaterThanOrEqual(1);
  expect(screen.getByText("json")).toBeInTheDocument();
  expect(screen.getByLabelText("工作区文件内容")).toHaveValue(
    "当前 server 未提供组织工作区文件读取接口，暂不能加载该文件内容。",
  );
});

it("routes an organization root to the empty structure state", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-empty/agents" && init?.method === "GET") return respond([]);
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-empty");

  expect(await screen.findByText("暂无智能体。创建首个智能体以建立组织架构。")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "新建智能体" })).toHaveAttribute(
    "href",
    "/orgs/org-empty/agents/new",
  );
});

it("loads organization settings from the avatar destination route", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1" && init?.method === "GET") {
      return respond({
        id: "org-1",
        name: "核心团队",
        description: "核心组织",
        requireBoardApprovalForNewAgents: true,
        defaultChatIssueCreationMode: "manual",
      });
    }
    if (path === "/api/orgs/org-1" && init?.method === "PATCH") {
      return respond({ id: "org-1", name: "核心团队" });
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/settings");

  expect(await screen.findByDisplayValue("核心团队")).toBeInTheDocument();
  expect(screen.getByLabelText("新建智能体需要审批")).toBeChecked();
  expect(screen.getByLabelText("默认聊天任务创建模式")).toHaveValue("manual");
  await userEvent.click(screen.getByLabelText("新建智能体需要审批"));
  await userEvent.selectOptions(screen.getByLabelText("默认聊天任务创建模式"), "disabled");
  await userEvent.click(screen.getByRole("button", { name: "保存组织" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1",
    expect.objectContaining({
      method: "PATCH",
      body: expect.stringContaining('"requireBoardApprovalForNewAgents":false'),
    }),
  );
  expect(screen.getByRole("button", { name: "保存组织" })).toBeInTheDocument();
  expect(screen.queryByRole("navigation", { name: "组织导航" })).not.toBeInTheDocument();
});
