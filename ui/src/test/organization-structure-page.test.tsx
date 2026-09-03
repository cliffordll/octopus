import { cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { renderApp, respond } from "./render-app";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("shows current reporting relationships in the organization structure", async () => {
  const members = [
    { id: "role-owner", orgId: "org-1", principalType: "user", principalId: "user-owner", displayName: "Owner", role: "owner", status: "active", reportsTo: null },
    { id: "role-ceo", orgId: "org-1", principalType: "agent", principalId: "agent-ceo", displayName: "Founder", role: "member", status: "active", reportsTo: "role-owner" },
    { id: "role-human", orgId: "org-1", principalType: "user", principalId: "user-1", displayName: "Human 1", role: "member", status: "active", reportsTo: "role-owner" },
    { id: "role-builder", orgId: "org-1", principalType: "agent", principalId: "agent-1", displayName: "Builder", role: "member", status: "active", reportsTo: "role-ceo" },
  ];
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs" && init?.method === "GET") {
      return respond([{ id: "org-1", name: "核心团队", status: "active" }]);
    }
    if (path === "/api/orgs/org-1/hierarchy") return respond(members);
    if (path === "/api/orgs/org-1/hierarchy/role-builder/manager" && init?.method === "PATCH") {
      return respond({ ...members[3], reportsTo: "role-human" });
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/structure");

  expect(await screen.findByRole("heading", { name: "组织架构" })).toBeInTheDocument();
  expect(screen.getAllByRole("heading", { name: "组织", level: 2 })).toHaveLength(1);
  expect(within(screen.getByRole("navigation", { name: "组织导航" })).queryByRole("heading", { name: "组织" })).not.toBeInTheDocument();
  expect(within(screen.getByRole("navigation", { name: "组织导航" })).getByRole("heading", { name: "组织管理" })).toBeInTheDocument();
  expect(within(screen.getByRole("navigation", { name: "组织导航" })).getByRole("heading", { name: "项目" })).toBeInTheDocument();
  expect(within(screen.getByRole("navigation", { name: "组织导航" })).getByRole("link", { name: "工作区" }))
    .toHaveAttribute("href", "/orgs/org-1/workspaces");
  expect(within(screen.getByRole("navigation", { name: "组织导航" })).getByRole("link", { name: "成员" }))
    .toHaveAttribute("href", "/orgs/org-1/members");
  expect(await screen.findByText("Builder")).toBeInTheDocument();
  expect(await screen.findByText("向 Founder 汇报")).toBeInTheDocument();
  expect(screen.getByText("Owner")).toBeInTheDocument();
  expect(screen.getByText("Human 1")).toBeInTheDocument();
  expect(screen.getByRole("region", { name: "组织关系画布" })).toContainElement(
    screen.getByTestId("organization-chart-canvas"),
  );

  await userEvent.click(screen.getByRole("button", { name: "调整架构" }));
  await userEvent.click(
    within(screen.getByRole("article", { name: /Builder/ })).getByRole("button", { name: "调整上级" }),
  );
  await userEvent.selectOptions(screen.getByRole("combobox", { name: "直属上级" }), "role-human");
  await userEvent.click(screen.getByRole("button", { name: "保存调整" }));

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/hierarchy/role-builder/manager",
    expect.objectContaining({ method: "PATCH", body: JSON.stringify({ managerId: "role-human" }) }),
  );
});

it("shows the organization workspace file tree and editor", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/projects" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/workspace/files?path=" && init?.method === "GET") {
      return respond({
        source: "org_root",
        rootPath: "C:/Users/test/.octopus/instances/default/organizations/org-1/workspaces",
        repoUrl: null,
        directoryPath: "",
        rootExists: true,
        entries: [
          { name: "agents", path: "agents", isDirectory: true, displayLabel: "智能体" },
          { name: "artifacts", path: "artifacts", isDirectory: true, displayLabel: "产物" },
          { name: "skills", path: "skills", isDirectory: true, displayLabel: "技能" },
          { name: "z-readme.md", path: "z-readme.md", isDirectory: false },
        ],
        message: null,
      });
    }
    if (path === "/api/orgs/org-1/workspace/files?path=artifacts" && init?.method === "GET") {
      return respond({
        source: "org_root",
        rootPath: "C:/Users/test/.octopus/instances/default/organizations/org-1/workspaces",
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
        rootPath: "C:/Users/test/.octopus/instances/default/organizations/org-1/workspaces",
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

  const workspaceHeading = await screen.findByRole("heading", { name: "工作区" });
  expect(workspaceHeading.closest(".org-content")).toHaveClass("organization-fullscreen-detail", "organization-workspaces-content");
  expect(screen.getByTestId("org-workspaces-files-card")).toBeInTheDocument();
  expect(screen.getByTestId("org-workspaces-editor-card")).toBeInTheDocument();
  expect(screen.getByTestId("org-workspaces-files-card").closest(".file-browser")).toHaveClass("framed");
  expect(screen.getByRole("heading", { name: "文件" })).toBeInTheDocument();
  expect(screen.queryByText("组织工作区根目录")).not.toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "内容" })).not.toBeInTheDocument();
  expect(screen.queryByText("Project Workspaces")).not.toBeInTheDocument();
  expect(screen.queryByRole("navigation", { name: "项目工作区" })).not.toBeInTheDocument();
  expect(await screen.findByText("artifacts")).toBeInTheDocument();
  expect(screen.getByText("skills")).toBeInTheDocument();
  expect(screen.getByText("agents")).toBeInTheDocument();
  const filesCard = within(screen.getByTestId("org-workspaces-files-card"));
  expect(filesCard.queryByText("智能体")).not.toBeInTheDocument();
  expect(filesCard.queryByText("产物")).not.toBeInTheDocument();
  expect(filesCard.queryByText("技能")).not.toBeInTheDocument();
  const fileButtons = within(screen.getByTestId("org-workspaces-files-card"))
    .getAllByRole("button")
    .map((button) => button.textContent ?? "");
  const topLevelOrder = ["agents", "artifacts", "skills"]
    .map((label) => fileButtons.findIndex((text) => text.includes(label)));
  expect(topLevelOrder.every((index) => index >= 0)).toBe(true);
  expect([...topLevelOrder].sort((left, right) => left - right)).toEqual(topLevelOrder);
  await userEvent.click(screen.getByRole("button", { name: /artifacts/ }));
  await userEvent.click(await screen.findByRole("button", { name: /summary.md/ }));
  expect(screen.getByRole("heading", { name: "summary.md · artifacts" })).toBeInTheDocument();
  expect(screen.getByText("只读")).toBeInTheDocument();
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
        rootPath: "C:/Users/test/.octopus/instances/default/organizations/org-1/workspaces",
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
        rootPath: "C:/Users/test/.octopus/instances/default/organizations/org-1/workspaces",
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
  const fetchMock = vi.fn((path: string) => {
    if (path === "/api/orgs/org-empty/hierarchy") return respond([]);
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-empty");

  expect(await screen.findByText("暂无组织成员。邀请 Human 或创建智能体以建立组织架构。")).toBeInTheDocument();
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

it("shows organization cost reporting on the organization costs route", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1" && init?.method === "GET") {
      return respond({
        id: "org-1",
        name: "核心团队",
        description: "核心组织",
        budgetMonthlyCents: 500000,
        requireBoardApprovalForNewAgents: false,
        defaultChatIssueCreationMode: "manual_approval",
      });
    }
    if (path === "/api/orgs/org-1/costs/summary" && init?.method === "GET") {
      return respond({ totalCostCents: 4234, eventCount: 7, inputTokens: 1200, outputTokens: 340 });
    }
    if (path === "/api/orgs/org-1/costs/by-agent" && init?.method === "GET") {
      return respond([{ agentId: "agent-1", costCents: 2300 }]);
    }
    if (path === "/api/orgs/org-1/costs/by-provider" && init?.method === "GET") {
      return respond([{ provider: "openai", costCents: 1800 }]);
    }
    if (path === "/api/orgs/org-1/costs/by-biller" && init?.method === "GET") {
      return respond([{ biller: "platform", costCents: 4234 }]);
    }
    if (path === "/api/orgs/org-1/costs/by-project" && init?.method === "GET") {
      return respond([{ projectId: "project-1", costCents: 900 }]);
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/costs");

  const costHeading = await screen.findByRole("heading", { name: "成本", level: 1 });
  const costHeader = costHeading.closest("header")!;
  expect(costHeader).toHaveClass("page-header");
  expect(costHeader.closest(".org-content")).toHaveClass("org-content-full", "organization-fullscreen-detail", "organization-costs-content");
  expect(costHeader.nextElementSibling).toHaveClass("tertiary-page-viewport", "tertiary-page-viewport-contained");
  expect(within(screen.getByRole("navigation", { name: "主导航" })).getByRole("link", { name: "组织" })).toHaveClass("active");
  expect(within(costHeader).getByText("Organization Costs")).toHaveClass("eyebrow");
  expect(within(costHeader).getByText("按智能体、服务商、计费方和项目查看运行成本。")).toHaveClass("tertiary-page-supporting");
  expect(screen.getAllByRole("heading", { name: "成本" })).toHaveLength(1);
  expect((await screen.findAllByText("$42.34")).length).toBeGreaterThanOrEqual(1);
  expect(screen.getByText("agent-1")).toBeInTheDocument();
  expect(screen.getByText("openai")).toBeInTheDocument();
  expect(screen.getByText("platform")).toBeInTheDocument();
  expect(screen.getByText("project-1")).toBeInTheDocument();
});

it("shows one informative empty state when the organization has no cost data", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/costs/summary" && init?.method === "GET") {
      return respond({ totalCostCents: 0, eventCount: 0, inputTokens: 0, outputTokens: 0 });
    }
    if (path.startsWith("/api/orgs/org-1/costs/") && init?.method === "GET") return respond([]);
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/costs");

  expect(await screen.findByRole("heading", { name: "暂无成本数据" })).toBeInTheDocument();
  expect(screen.getByText("智能体运行并上报 token 与费用后，成本会自动出现在这里。")).toBeInTheDocument();
  expect(screen.getByLabelText("成本汇总维度")).toHaveTextContent("智能体Provider计费方项目");
  expect(screen.queryByRole("heading", { name: "按智能体" })).not.toBeInTheDocument();
  expect(screen.queryByText("暂无成本记录。")).not.toBeInTheDocument();
});
