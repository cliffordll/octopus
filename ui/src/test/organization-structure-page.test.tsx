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
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/projects" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/workspace/files?path=" && init?.method === "GET") {
      return respond({
        source: "org_root",
        rootPath: "D:/coding/octopus/.octopus/organizations/org-1/workspaces",
        repoUrl: null,
        directoryPath: "",
        rootExists: true,
        entries: [
          { name: "agents", path: "agents", isDirectory: true },
          { name: "artifacts", path: "artifacts", isDirectory: true },
          { name: "skills", path: "skills", isDirectory: true },
        ],
        message: null,
      });
    }
    if (path === "/api/orgs/org-1/workspace/files?path=artifacts" && init?.method === "GET") {
      return respond({
        source: "org_root",
        rootPath: "D:/coding/octopus/.octopus/organizations/org-1/workspaces",
        repoUrl: null,
        directoryPath: "artifacts",
        rootExists: true,
        entries: [{ name: "summary.md", path: "artifacts/summary.md", isDirectory: false }],
        message: null,
      });
    }
    if (path === "/api/orgs/org-1/workspace/file?path=artifacts%2Fsummary.md" && init?.method === "GET") {
      return respond({
        source: "org_root",
        rootPath: "D:/coding/octopus/.octopus/organizations/org-1/workspaces",
        repoUrl: null,
        filePath: "artifacts/summary.md",
        rootExists: true,
        content: "# Summary\n\nhello",
        contentType: "text/markdown",
        previewKind: "text",
        contentPath: null,
        message: null,
        truncated: false,
      });
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
  expect(await screen.findByText("artifacts")).toBeInTheDocument();
  expect(screen.getByText("skills")).toBeInTheDocument();
  expect(screen.getByText("agents")).toBeInTheDocument();
  const fileButtons = within(screen.getByTestId("org-workspaces-files-card"))
    .getAllByRole("button")
    .map((button) => button.textContent ?? "");
  const topLevelOrder = ["agents", "artifacts", "skills"]
    .map((label) => fileButtons.findIndex((text) => text.includes(label)));
  expect(topLevelOrder.every((index) => index >= 0)).toBe(true);
  expect([...topLevelOrder].sort((left, right) => left - right)).toEqual(topLevelOrder);
  await userEvent.click(screen.getByRole("button", { name: /artifacts/ }));
  await userEvent.click(await screen.findByRole("button", { name: /summary.md/ }));
  expect(await screen.findByLabelText("工作区文件内容")).toHaveValue("# Summary\n\nhello");
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/workspace/files?path=artifacts",
    expect.objectContaining({ method: "GET" }),
  );
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/workspace/file?path=artifacts%2Fsummary.md",
    expect.objectContaining({ method: "GET" }),
  );
  expect(screen.queryByText("已配置代码库")).not.toBeInTheDocument();
});

it("keeps the selected workspace file from the path query", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/projects" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/workspace/files?path=" && init?.method === "GET") {
      return respond({
        source: "org_root",
        rootPath: "D:/coding/octopus/.octopus/organizations/org-1/workspaces",
        repoUrl: null,
        directoryPath: "",
        rootExists: true,
        entries: [],
        message: "This folder is empty.",
      });
    }
    if (path === "/api/orgs/org-1/workspace/file?path=package-lock.json" && init?.method === "GET") {
      return respond({
        source: "org_root",
        rootPath: "D:/coding/octopus/.octopus/organizations/org-1/workspaces",
        repoUrl: null,
        filePath: "package-lock.json",
        rootExists: true,
        content: "{}",
        contentType: "application/json",
        previewKind: "text",
        contentPath: null,
        message: null,
        truncated: false,
      });
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/workspaces?path=package-lock.json");

  expect(await screen.findByRole("heading", { name: "工作区" })).toBeInTheDocument();
  expect(screen.getAllByText("package-lock.json").length).toBeGreaterThanOrEqual(1);
  expect(screen.getByText("json")).toBeInTheDocument();
  expect(await screen.findByLabelText("工作区文件内容")).toHaveValue("{}");
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
        defaultChatIssueCreationMode: "manual_approval",
      });
    }
    if (path === "/api/orgs/org-1" && init?.method === "PATCH") {
      return respond({ id: "org-1", name: "核心团队" });
    }
    if (path === "/api/orgs/org-1/archive" && init?.method === "POST") {
      return respond({ id: "org-1", name: "核心团队", status: "archived" });
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/settings");

  expect(await screen.findByDisplayValue("核心团队")).toBeInTheDocument();
  expect(screen.getByLabelText("新建智能体需要审批")).toBeChecked();
  expect(screen.getByLabelText("默认聊天任务创建模式")).toHaveValue("manual_approval");
  await userEvent.click(screen.getByLabelText("新建智能体需要审批"));
  await userEvent.selectOptions(screen.getByLabelText("默认聊天任务创建模式"), "auto_create");
  await userEvent.click(screen.getByRole("button", { name: "保存组织" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1",
    expect.objectContaining({
      method: "PATCH",
      body: expect.stringContaining('"requireBoardApprovalForNewAgents":false'),
    }),
  );
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1",
    expect.objectContaining({
      method: "PATCH",
      body: expect.stringContaining('"defaultChatIssueCreationMode":"auto_create"'),
    }),
  );
  expect(screen.getByRole("button", { name: "保存组织" })).toBeInTheDocument();
  expect(screen.queryByRole("navigation", { name: "组织导航" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "归档组织" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/archive",
    expect.objectContaining({ method: "POST" }),
  );
});
