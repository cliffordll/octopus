import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { renderApp, respond } from "./render-app";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("updates a project and manages its resource attachments", async () => {
  const project = {
    id: "project-1",
    orgId: "org-1",
    urlKey: "console",
    goalId: null,
    name: "控制台",
    description: "原描述",
    status: "planned",
    leadAgentId: null,
    targetDate: "2026-06-01",
    color: null,
    pauseReason: null,
    pausedAt: null,
    codebase: {
      configured: true,
      scope: "project",
      workspaceId: "workspace-1",
      repoUrl: "https://example.com/octopus.git",
      repoRef: "main",
      defaultRef: "main",
      repoName: "octopus",
      localFolder: "D:/coding/octopus",
      managedFolder: "organizations/org-1/workspaces",
      effectiveLocalFolder: "D:/coding/octopus",
      origin: "project_workspace",
    },
    workspaces: [
      {
        id: "workspace-1",
        orgId: "org-1",
        projectId: "project-1",
        name: "默认代码来源",
        sourceType: "git",
        cwd: "D:/coding/octopus",
        repoUrl: "https://example.com/octopus.git",
        repoRef: "main",
        defaultRef: "main",
        visibility: "shared",
        setupCommand: "npm install",
        cleanupCommand: null,
        remoteProvider: null,
        remoteWorkspaceRef: null,
        sharedWorkspaceKey: "console-main",
        metadata: null,
        executionWorkspacePolicy: {
          enabled: true,
          defaultMode: "shared_workspace",
          branchPolicy: { baseRef: "develop" },
        },
        isPrimary: true,
        createdAt: "2026-05-28T09:00:00Z",
        updatedAt: "2026-05-28T10:00:00Z",
      },
    ],
    primaryWorkspace: null,
    resources: [
      {
        id: "attachment-1",
        orgId: "org-1",
        projectId: "project-1",
        resourceId: "resource-1",
        role: "working_set",
        note: null,
        sortOrder: 0,
        resource: {
          id: "resource-1",
          orgId: "org-1",
          name: "Repository",
          kind: "directory",
          locator: "D:/coding/octopus",
          description: "主仓库",
          metadata: null,
          createdAt: "",
          updatedAt: "",
        },
        createdAt: "",
        updatedAt: "",
      },
    ],
    archivedAt: null,
    createdAt: "",
    updatedAt: "2026-05-28T16:00:00Z",
  };
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/projects/project-1" && init?.method === "GET") return respond(project);
    if (path === "/api/orgs/org-1/projects" && init?.method === "GET") return respond([project]);
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([{ id: "agent-1", name: "Builder", role: "engineer", status: "idle" }]);
    }
    if (path === "/api/orgs/org-1/resources" && init?.method === "GET") {
      return respond([
        project.resources[0].resource,
        {
          id: "resource-2",
          orgId: "org-1",
          name: "设计规范",
          kind: "url",
          locator: "https://example.com/spec",
          description: "上游参考",
          metadata: null,
          createdAt: "",
          updatedAt: "",
        },
      ]);
    }
    if (path === "/api/orgs/org-1/resources" && init?.method === "POST") {
      return respond({
        id: "resource-3",
        orgId: "org-1",
        name: "设计文档",
        kind: "url",
        locator: "https://example.com/design",
        description: "上游参考",
        metadata: null,
        createdAt: "",
        updatedAt: "",
      });
    }
    if (path.endsWith("/resources") && init?.method === "GET") return respond(project.resources);
    if (path === "/api/orgs/org-1/issues?projectId=project-1" && init?.method === "GET") {
      return respond([
        {
          id: "issue-1",
          orgId: "org-1",
          identifier: "OCT-1",
          title: "完成控制台导航",
          status: "in_progress",
          priority: "high",
          projectId: "project-1",
          assigneeAgentId: "agent-1",
          assigneeUserId: null,
          createdAt: "2026-05-28T10:00:00Z",
          updatedAt: "2026-05-28T11:00:00Z",
        },
        {
          id: "issue-2",
          orgId: "org-1",
          identifier: "OCT-2",
          title: "等待接口确认",
          status: "blocked",
          priority: "medium",
          projectId: "project-1",
          assigneeAgentId: null,
          assigneeUserId: null,
          createdAt: "2026-05-28T12:00:00Z",
          updatedAt: "2026-05-28T13:00:00Z",
        },
        {
          id: "issue-3",
          orgId: "org-1",
          identifier: "OCT-3",
          title: "整理验收记录",
          status: "done",
          priority: "low",
          projectId: "project-1",
          assigneeAgentId: null,
          assigneeUserId: null,
          createdAt: "2026-05-28T14:00:00Z",
          updatedAt: "2026-05-28T15:00:00Z",
        },
      ]);
    }
    return respond(project);
  });
  vi.stubGlobal("fetch", fetchMock);

  const { container } = renderApp("/orgs/org-1/projects/project-1");
  expect(await screen.findByRole("heading", { name: "控制台" })).toBeInTheDocument();
  expect(container.querySelector(".project-summary-grid")).toBeNull();
  const tabs = screen.getByRole("navigation", { name: "项目详情导航" });
  expect(within(tabs).getByRole("link", { name: "配置" })).toHaveAttribute(
    "href",
    "/orgs/org-1/projects/project-1/configuration",
  );
  expect(within(tabs).getByRole("link", { name: "资源" })).toHaveAttribute(
    "href",
    "/orgs/org-1/projects/project-1/resources",
  );
  expect(within(tabs).getByRole("link", { name: "任务" })).toHaveAttribute(
    "href",
    "/orgs/org-1/projects/project-1/issues",
  );
  expect(within(tabs).getByRole("link", { name: "预算" })).toHaveAttribute(
    "href",
    "/orgs/org-1/projects/project-1/budget",
  );
  expect(screen.getByRole("heading", { name: "项目工作区" })).toBeInTheDocument();
  expect(screen.getByTitle("https://example.com/octopus.git · main")).toBeInTheDocument();
  expect(screen.getAllByText("console-main").length).toBeGreaterThanOrEqual(1);

  await userEvent.clear(screen.getByLabelText("描述"));
  await userEvent.type(screen.getByLabelText("描述"), "更新后的描述");
  await userEvent.selectOptions(screen.getByLabelText("负责人"), "agent-1");
  await userEvent.clear(screen.getByLabelText("目标日期"));
  await userEvent.type(screen.getByLabelText("目标日期"), "2026-06-01");
  await userEvent.type(
    screen.getByLabelText("目标 ID"),
    "11111111-1111-4111-8111-111111111111,22222222-2222-4222-8222-222222222222",
  );
  await userEvent.selectOptions(screen.getByLabelText("默认代码来源 执行模式"), "isolated_workspace");
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/projects/project-1/workspaces/workspace-1",
    expect.objectContaining({
      method: "PATCH",
      body: JSON.stringify({
          executionWorkspacePolicy: {
            enabled: true,
            defaultMode: "isolated_workspace",
            branchPolicy: { baseRef: "develop" },
            workspaceStrategy: { mode: "isolated_workspace" },
          },
      }),
    }),
  );
  await userEvent.click(screen.getByRole("button", { name: "保存基础信息" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/projects/project-1",
    expect.objectContaining({
      method: "PATCH",
      body: JSON.stringify({
        description: "更新后的描述",
        name: "控制台",
        status: "planned",
        leadAgentId: "agent-1",
        targetDate: "2026-06-01",
        goalIds: ["11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"],
      }),
    }),
  );

  await userEvent.click(within(tabs).getByRole("link", { name: "资源" }));
  expect(await screen.findByText("Repository")).toBeInTheDocument();
  await userEvent.selectOptions(screen.getByLabelText("项目角色"), "reference");
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/projects/project-1/resources/attachment-1",
    expect.objectContaining({
      method: "PATCH",
      body: JSON.stringify({ role: "reference", note: null, sortOrder: 0 }),
    }),
  );
  await userEvent.click(screen.getByRole("button", { name: "附加已有" }));
  await userEvent.click(await screen.findByRole("button", { name: /设计规范/ }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/projects/project-1/resources",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ resourceId: "resource-2", role: "reference", sortOrder: 1 }),
    }),
  );
  await userEvent.click(screen.getByRole("button", { name: "新增资源" }));
  await userEvent.type(screen.getByLabelText("名称"), "设计文档");
  await userEvent.selectOptions(screen.getByLabelText("类型"), "url");
  await userEvent.type(screen.getByLabelText("定位"), "https://example.com/design");
  await userEvent.type(screen.getByLabelText("说明"), "上游参考");
  await userEvent.selectOptions(screen.getAllByLabelText("项目角色").at(-1) as HTMLElement, "reference");
  await userEvent.type(screen.getAllByLabelText("项目备注").at(-1) as HTMLElement, "先读这个");
  await userEvent.click(screen.getByRole("button", { name: "创建并附加" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/resources",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        name: "设计文档",
        kind: "url",
        locator: "https://example.com/design",
        description: "上游参考",
      }),
    }),
  );
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/projects/project-1/resources",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ resourceId: "resource-3", role: "reference", note: "先读这个", sortOrder: 1 }),
    }),
  );

  await userEvent.click(within(screen.getByRole("navigation", { name: "项目详情导航" })).getByRole("link", { name: "任务" }));
  expect(await screen.findByRole("link", { name: "完成控制台导航" })).toHaveAttribute(
    "href",
    "/orgs/org-1/issues/issue-1",
  );
  const projectIssueCard = screen.getByRole("link", { name: "完成控制台导航" }).closest(".project-issue-status-row");
  expect(projectIssueCard).not.toBeNull();
  expect(projectIssueCard).toHaveTextContent("创建时间");
  expect(projectIssueCard).toHaveTextContent("2026年5月28日 18:00");
  expect(projectIssueCard).toHaveTextContent("归属");
  expect(projectIssueCard).toHaveTextContent("Builder");
  const issueSummary = screen.getByText("总数").closest(".project-issue-status-summary");
  expect(issueSummary).not.toBeNull();
  expect(within(issueSummary as HTMLElement).getByText("总数").closest(".summary-metric")).toHaveTextContent("3");
  expect(within(issueSummary as HTMLElement).getByText("活跃").closest(".summary-metric")).toHaveTextContent("2");
  expect(within(issueSummary as HTMLElement).getByText("阻塞").closest(".summary-metric")).toHaveTextContent("1");
  expect(within(issueSummary as HTMLElement).getByText("已完成").closest(".summary-metric")).toHaveTextContent("1");
  expect(screen.getByRole("heading", { name: "进行中" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "阻塞" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "已完成" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "等待接口确认" })).toHaveAttribute(
    "href",
    "/orgs/org-1/issues/issue-2",
  );
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/issues?projectId=project-1",
    expect.objectContaining({ method: "GET" }),
  );
  await userEvent.click(screen.getByRole("button", { name: "删除项目" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/projects/project-1",
    expect.objectContaining({ method: "DELETE" }),
  );
}, 10_000);

it("uses organization scratch when the project has no workspace", async () => {
  const project = {
    id: "project-1",
    orgId: "org-1",
    urlKey: "console",
    goalId: null,
    goalIds: [],
    goals: [],
    name: "控制台",
    description: null,
    status: "planned",
    leadAgentId: null,
    targetDate: null,
    color: null,
    pauseReason: null,
    pausedAt: null,
    codebase: { configured: false, scope: "none", managedFolder: "organizations/org-1/workspaces", effectiveLocalFolder: "organizations/org-1/workspaces", origin: "managed_checkout" },
    workspaces: [],
    primaryWorkspace: null,
    resources: [],
    archivedAt: null,
    createdAt: "",
    updatedAt: "",
  };
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/projects/project-1" && init?.method === "GET") return respond(project);
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") return respond([]);
    return respond(project);
  });
  vi.stubGlobal("fetch", fetchMock);

  const { container } = renderApp("/orgs/org-1/projects/project-1/configuration");
  expect(await screen.findByRole("heading", { name: "项目工作区" })).toBeInTheDocument();
  const flowHeadings = Array.from(container.querySelectorAll(".project-config-section h2"), (heading) => heading.textContent);
  expect(flowHeadings).toEqual(["基础信息", "项目工作区", "组织草稿与产物", "任务运行记录"]);
  expect(screen.getByText("organizations/org-1/workspaces/artifacts")).toBeInTheDocument();
  expect(screen.getByText("尚未配置项目工作区")).toBeInTheDocument();
  expect(screen.getByText(/代码任务需先添加代码来源并选择执行模式/)).toBeInTheDocument();
  expect(screen.queryByLabelText("控制台 执行模式")).not.toBeInTheDocument();
});

it("blocks project configuration save when goal IDs are not UUIDs", async () => {
  const project = {
    id: "project-1",
    orgId: "org-1",
    urlKey: "console",
    goalId: null,
    goalIds: [],
    goals: [],
    name: "控制台",
    description: null,
    status: "planned",
    leadAgentId: null,
    targetDate: null,
    color: null,
    pauseReason: null,
    pausedAt: null,
    codebase: { configured: false, scope: "none", managedFolder: "organizations/org-1/workspaces", effectiveLocalFolder: "organizations/org-1/workspaces", origin: "managed_checkout" },
    workspaces: [],
    primaryWorkspace: null,
    resources: [],
    archivedAt: null,
    createdAt: "",
    updatedAt: "",
  };
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/projects/project-1" && init?.method === "GET") return respond(project);
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") return respond([]);
    return respond(project);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/projects/project-1/configuration");
  expect(await screen.findByRole("heading", { name: "基础信息" })).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("目标 ID"), "goal-1");
  await userEvent.click(screen.getByRole("button", { name: "保存基础信息" }));

  expect(await screen.findByText("目标 ID 必须是 UUID，多个目标请用逗号分隔。")).toBeInTheDocument();
  expect(fetchMock).not.toHaveBeenCalledWith(
    "/api/projects/project-1",
    expect.objectContaining({ method: "PATCH" }),
  );
});

it("manages project workspaces from the configuration tab", async () => {
  const project = {
    id: "project-1",
    orgId: "org-1",
    urlKey: "console",
    goalId: null,
    goalIds: [],
    goals: [],
    name: "控制台",
    description: null,
    status: "planned",
    leadAgentId: null,
    targetDate: null,
    color: null,
    pauseReason: null,
    pausedAt: null,
    codebase: { configured: true, scope: "project", managedFolder: "organizations/org-1/workspaces", effectiveLocalFolder: "D:/coding/old", localFolder: "D:/coding/old", origin: "local_folder" },
    workspaces: [
      {
        id: "workspace-1",
        orgId: "org-1",
        projectId: "project-1",
        name: "旧工作区",
        sourceType: "local_path",
        cwd: "D:/coding/old",
        repoUrl: null,
        repoRef: null,
        defaultRef: null,
        visibility: "default",
        setupCommand: null,
        cleanupCommand: null,
        remoteProvider: null,
        remoteWorkspaceRef: null,
        sharedWorkspaceKey: null,
        metadata: null,
        executionWorkspacePolicy: { enabled: true, defaultMode: "shared_workspace" },
        isPrimary: true,
        createdAt: "",
        updatedAt: "",
      },
      {
        id: "workspace-2",
        orgId: "org-1",
        projectId: "project-1",
        name: "备用工作区",
        sourceType: "local_path",
        cwd: "D:/coding/backup",
        repoUrl: null,
        repoRef: null,
        defaultRef: null,
        visibility: "default",
        setupCommand: null,
        cleanupCommand: null,
        remoteProvider: null,
        remoteWorkspaceRef: null,
        sharedWorkspaceKey: null,
        metadata: null,
        executionWorkspacePolicy: { enabled: true, defaultMode: "isolated_workspace" },
        isPrimary: false,
        createdAt: "",
        updatedAt: "",
      },
    ],
    primaryWorkspace: null,
    resources: [],
    archivedAt: null,
    createdAt: "",
    updatedAt: "",
  };
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/projects/project-1" && init?.method === "GET") return respond(project);
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/projects" && init?.method === "GET") return respond([project]);
    if (path === "/api/projects/project-1/workspaces" && init?.method === "POST") {
      return respond({ ...project.workspaces[0], id: "workspace-3", name: "新工作区" });
    }
    if (path === "/api/projects/project-1/workspaces/workspace-2" && init?.method === "PATCH") {
      return respond({ ...project.workspaces[1], isPrimary: true });
    }
    if (path === "/api/projects/project-1/workspaces/workspace-1" && init?.method === "DELETE") {
      return respond(project.workspaces[0]);
    }
    return respond(project);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/projects/project-1/configuration");

  expect(await screen.findByRole("heading", { name: "项目工作区" })).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("代码来源本地 cwd"), "D:/coding/new");
  await userEvent.click(screen.getByRole("button", { name: "添加工作区" }));
  expect(screen.getByText("请先填写代码来源名称。")).toBeInTheDocument();
  await userEvent.clear(screen.getByLabelText("代码来源本地 cwd"));
  await userEvent.type(screen.getByLabelText("代码来源名称"), "新工作区");
  await userEvent.click(screen.getByRole("button", { name: "添加工作区" }));
  expect(screen.getByText("本地 cwd 和仓库 URL 至少填写一项。")).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("代码来源本地 cwd"), "D:/coding/new");
  await userEvent.type(screen.getByLabelText("代码来源仓库 URL"), "https://example.com/new.git");
  await userEvent.type(screen.getByLabelText("代码来源分支"), "main");
  await userEvent.selectOptions(screen.getByLabelText("新工作区执行模式"), "operator_branch");
  await userEvent.click(screen.getByRole("button", { name: "添加工作区" }));
  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/projects/project-1/workspaces",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          name: "新工作区",
          sourceType: "git_repo",
          cwd: "D:/coding/new",
          repoUrl: "https://example.com/new.git",
          repoRef: "main",
          defaultRef: "main",
          executionWorkspacePolicy: {
            enabled: true,
            defaultMode: "operator_branch",
            workspaceStrategy: { mode: "operator_branch" },
          },
        }),
      }),
    );
  });

  await userEvent.click(screen.getAllByRole("button", { name: "设为默认" })[1]);
  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/projects/project-1/workspaces/workspace-2",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({ isPrimary: true }),
      }),
    );
  });

  const deleteButtons = screen.getAllByRole("button", { name: "删除代码来源" });
  expect(deleteButtons[0]).toBeDisabled();
  expect(deleteButtons[0]).toHaveAttribute("title", "请先将另一个工作区设为默认");
  await userEvent.click(deleteButtons[1]);
  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/projects/project-1/workspaces/workspace-2",
      expect.objectContaining({ method: "DELETE" }),
    );
  });
});
