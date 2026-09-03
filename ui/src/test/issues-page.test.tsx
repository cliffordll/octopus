import { cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { renderApp, respond } from "./render-app";

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.unstubAllGlobals();
});

it("groups issues by status and creates issues for an organization", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/projects" && init?.method === "GET") {
      return respond([{ id: "project-1", orgId: "org-1", name: "控制台", status: "in_progress", urlKey: "console" }]);
    }
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([
        { id: "agent-1", name: "Builder", role: "engineer", status: "idle" },
        { id: "agent-2", name: "Reviewer", role: "qa", status: "idle" },
      ]);
    }
    if (path.startsWith("/api/orgs/org-1/issues") && init?.method === "GET") {
      return respond([
        {
          id: "issue-1",
          orgId: "org-1",
          identifier: "OCT-1",
          title: "实现登录流程",
          status: "in_progress",
          priority: "high",
          projectId: null,
          goalId: null,
          assigneeAgentId: "agent-1",
          assigneeUserId: null,
          originKind: "manual",
          originId: null,
          createdAt: "2026-05-28T10:00:00Z",
          updatedAt: "2026-05-28T11:00:00Z",
        },
      ]);
    }
    return respond({ id: "issue-2", title: "核对发布说明" });
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/issues");
  const pageHeader = screen.getByRole("heading", { name: "全部任务" }).closest("header")!;
  expect(within(pageHeader).getByText("Issues")).toHaveClass("eyebrow");
  expect(within(pageHeader).getByText("查看组织内全部任务，按状态跟进执行进度与负责人。")).toHaveClass("tertiary-page-supporting");
  expect(await screen.findByRole("link", { name: "实现登录流程" })).toHaveAttribute(
    "href",
    "/orgs/org-1/issues/issue-1",
  );
  const issueCard = screen.getByRole("link", { name: "实现登录流程" }).closest(".project-issue-status-row");
  expect(issueCard).not.toBeNull();
  const columnHeaders = screen.getByText("任务编号 标题").parentElement!;
  expect(within(columnHeaders).getByText("项目")).toBeInTheDocument();
  expect(within(columnHeaders).getByText("执行者")).toBeInTheDocument();
  expect(within(columnHeaders).getByText("优先级")).toBeInTheDocument();
  expect(within(columnHeaders).getByText("更新时间")).toBeInTheDocument();
  expect(issueCard).toHaveTextContent("OCT-1");
  expect(issueCard).toHaveTextContent("Builder");
  expect(screen.queryByLabelText("状态筛选")).not.toBeInTheDocument();
  const issueSummary = screen.getByText("总数").closest(".project-issue-status-summary");
  expect(issueSummary).not.toBeNull();
  expect(within(issueSummary as HTMLElement).getByText("总数").closest(".project-summary-chip")).toHaveTextContent("1");
  expect(within(issueSummary as HTMLElement).getByText("活跃").closest(".project-summary-chip")).toHaveTextContent("1");
  expect(screen.getByRole("heading", { name: "进行中" })).toBeInTheDocument();

  expect(screen.queryByLabelText("任务名称")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "新建任务" }));
  const dialog = within(screen.getByRole("dialog", { name: "新建任务" }));
  await userEvent.type(dialog.getByLabelText("任务名称"), "核对发布说明");
  await userEvent.selectOptions(dialog.getByLabelText("负责人"), "agent:agent-1");
  expect(within(dialog.getByLabelText("Reviewer")).getByRole("option", { name: "Builder" })).toBeDisabled();
  await userEvent.selectOptions(dialog.getByLabelText("项目"), "project-1");
  await userEvent.selectOptions(dialog.getByLabelText("Reviewer"), "agent-2");
  await userEvent.selectOptions(dialog.getByLabelText("模型配置"), "gpt-5-codex");
  await userEvent.type(dialog.getByLabelText("描述"), "检查发布说明和变更范围");
  await userEvent.selectOptions(dialog.getByLabelText("代办"), "todo");
  await userEvent.selectOptions(dialog.getByLabelText("优先级"), "high");
  await userEvent.click(dialog.getByRole("button", { name: "创建任务" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/issues",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        title: "核对发布说明",
        description: "检查发布说明和变更范围",
        projectId: "project-1",
        assigneeAgentId: "agent-1",
        reviewerAgentId: "agent-2",
        priority: "high",
        status: "todo",
      }),
    }),
  );
});

it("assigns tasks to Humans and filters the current Human inbox", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/projects" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/hierarchy") {
      return respond([
        {
          id: "role-user-1",
          orgId: "org-1",
          principalType: "user",
          principalId: "test-user",
          displayName: "Human 1",
          role: "member",
          status: "active",
          reportsTo: null,
        },
      ]);
    }
    if (path === "/api/orgs/org-1/issues?assigneeUserId=test-user" && init?.method === "GET") {
      return respond([
        {
          id: "human-issue",
          orgId: "org-1",
          identifier: "OCT-2",
          title: "人工确认发布",
          status: "todo",
          priority: "medium",
          projectId: null,
          goalId: null,
          assigneeAgentId: null,
          assigneeUserId: "test-user",
          originKind: "delegation",
          originId: null,
          updatedAt: "2026-08-28T10:00:00Z",
        },
      ]);
    }
    if (path === "/api/orgs/org-1/issues" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/issues" && init?.method === "POST") {
      return respond({ id: "human-issue", title: "人工确认发布" });
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/issues");
  await userEvent.click(await screen.findByRole("button", { name: "新建任务" }));
  const dialog = within(screen.getByRole("dialog", { name: "新建任务" }));
  await userEvent.type(dialog.getByLabelText("任务名称"), "人工确认发布");
  await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/hierarchy",
    expect.any(Object),
  ));
  await dialog.findByRole("option", { name: "Human 1（Human）" });
  await userEvent.selectOptions(dialog.getByLabelText("负责人"), "user:test-user");
  expect(dialog.getByLabelText("模型配置")).toBeDisabled();
  await userEvent.click(dialog.getByRole("button", { name: "创建任务" }));

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/issues",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        title: "人工确认发布",
        assigneeUserId: "test-user",
        priority: "medium",
        status: "todo",
      }),
    }),
  );

  await userEvent.click(screen.getByRole("link", { name: "我的任务" }));
  expect(await screen.findByRole("link", { name: "人工确认发布" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "我的任务" })).toHaveClass("active");
  expect(screen.getByRole("link", { name: "全部任务" })).not.toHaveClass("active");
  expect(screen.getByRole("heading", { name: "我的任务" })).toBeInTheDocument();
  expect(screen.getByText("查看当前账号负责的任务，集中跟进自己的工作。")).toBeInTheDocument();
  expect(screen.queryByText("执行者")).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "人工确认发布" })).not.toHaveTextContent("Human 1");
});

it("groups task navigation by shortcuts, collapsed recent views, and project links", async () => {
  localStorage.setItem(
    "octopus:recent-issues:org-1",
    JSON.stringify([
      { id: "issue-recent-1", title: "最近处理 1", identifier: "OCT-9", status: "todo" },
      { id: "issue-recent-2", title: "最近处理 2", identifier: "OCT-10", status: "todo" },
      { id: "issue-recent-3", title: "最近处理 3", identifier: "OCT-11", status: "todo" },
      { id: "issue-recent-4", title: "最近处理 4", identifier: "OCT-12", status: "todo" },
      { id: "issue-recent-5", title: "最近处理 5", identifier: "OCT-13", status: "todo" },
      { id: "issue-recent-6", title: "最近处理 6", identifier: "OCT-14", status: "todo" },
    ]),
  );
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/projects" && init?.method === "GET") {
      return respond([
        { id: "project-1", orgId: "org-1", name: "控制台", status: "in_progress", urlKey: "console" },
        { id: "project-2", orgId: "org-1", name: "增长", status: "planned", urlKey: "growth" },
        { id: "project-empty", orgId: "org-1", name: "空项目", status: "planned", urlKey: "empty" },
      ]);
    }
    if (path === "/api/orgs/org-1/issues?status=backlog" && init?.method === "GET") {
      return respond([
        {
          id: "issue-draft",
          orgId: "org-1",
          identifier: "OCT-3",
          title: "整理草稿",
          status: "backlog",
          priority: "medium",
          projectId: null,
          goalId: null,
          assigneeAgentId: "agent-1",
          assigneeUserId: null,
          originKind: "manual",
          originId: null,
          createdAt: "2026-05-28T09:00:00Z",
          updatedAt: "2026-05-28T09:30:00Z",
        },
      ]);
    }
    if (path === "/api/orgs/org-1/issues?projectId=project-empty" && init?.method === "GET") {
      return respond([]);
    }
    if (path === "/api/orgs/org-1/issues" && init?.method === "GET") {
      return respond([
        {
          id: "issue-1",
          orgId: "org-1",
          identifier: "OCT-1",
          title: "实现登录流程",
          status: "in_progress",
          priority: "high",
          projectId: "project-1",
          goalId: null,
          assigneeAgentId: null,
          assigneeUserId: null,
          originKind: "manual",
          originId: null,
          updatedAt: "",
        },
        {
          id: "issue-2",
          orgId: "org-1",
          identifier: "OCT-2",
          title: "设计增长实验",
          status: "blocked",
          priority: "low",
          projectId: "project-2",
          goalId: null,
          assigneeAgentId: null,
          assigneeUserId: null,
          originKind: "manual",
          originId: null,
          updatedAt: "",
        },
      ]);
    }
    return respond({ id: "issue-4" });
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/issues");

  const taskNavigation = screen.getByRole("navigation", { name: "任务导航" });
  const taskSidebar = taskNavigation.closest("aside")!;
  expect(within(taskSidebar).getByText("Issues")).toHaveClass("org-sidebar-label");
  expect(within(taskNavigation).queryByRole("heading", { name: "任务" })).not.toBeInTheDocument();
  expect(within(taskNavigation).getByRole("heading", { name: "任务视图" })).toBeInTheDocument();
  expect(screen.getAllByRole("heading", { name: "任务", level: 2 })).toHaveLength(1);
  expect(within(taskNavigation).getByRole("link", { name: "全部任务" })).toHaveAttribute("href", "/orgs/org-1/issues");
  expect(within(taskNavigation).getByRole("link", { name: "我的任务" })).toHaveAttribute(
    "href",
    "/orgs/org-1/issues?mine=1",
  );
  expect(within(taskNavigation).getByRole("link", { name: "草稿任务" })).toHaveAttribute(
    "href",
    "/orgs/org-1/issues?status=backlog",
  );
  expect(within(taskNavigation).queryByRole("link", { name: "关注中" })).not.toBeInTheDocument();
  expect(within(taskNavigation).getByText("最近查看")).toBeInTheDocument();
  expect(within(taskNavigation).getByRole("link", { name: /最近处理 1/ })).toHaveAttribute(
    "href",
    "/orgs/org-1/issues/issue-recent-1",
  );
  expect(within(taskNavigation).getByRole("link", { name: /最近处理 5/ })).toBeInTheDocument();
  expect(within(taskNavigation).queryByRole("link", { name: /最近处理 6/ })).not.toBeInTheDocument();
  await userEvent.click(within(taskNavigation).getByRole("button", { name: "展开全部 6" }));
  expect(within(taskNavigation).getByRole("link", { name: /最近处理 6/ })).toBeInTheDocument();
  await userEvent.click(within(taskNavigation).getByRole("button", { name: "收起" }));
  expect(within(taskNavigation).queryByRole("link", { name: /最近处理 6/ })).not.toBeInTheDocument();
  expect(within(taskNavigation).getByText("项目")).toBeInTheDocument();
  expect(await within(taskNavigation).findByRole("link", { name: "控制台" })).toHaveAttribute(
    "href",
    "/orgs/org-1/issues?projectId=project-1",
  );
  expect(within(taskNavigation).queryByRole("link", { name: /实现登录流程/ })).not.toBeInTheDocument();
  expect(taskNavigation).not.toHaveTextContent("in_progress");
  expect(within(taskNavigation).getByRole("link", { name: "增长" })).toHaveAttribute(
    "href",
    "/orgs/org-1/issues?projectId=project-2",
  );
  expect(within(taskNavigation).queryByRole("link", { name: /设计增长实验/ })).not.toBeInTheDocument();
  expect(taskNavigation).not.toHaveTextContent("blocked");
  expect(within(taskNavigation).getByRole("link", { name: "空项目" })).toHaveAttribute(
    "href",
    "/orgs/org-1/issues?projectId=project-empty",
  );
  expect(taskNavigation).not.toHaveTextContent("暂无任务");
  for (const link of within(taskNavigation).getAllByRole("link")) {
    expect(link.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    expect(link.querySelector(".context-entry-icon")?.textContent?.trim()).toBe("");
  }
  expect(within(taskNavigation).getByRole("link", { name: /最近处理 1/ })).toHaveTextContent("OCT-9");

  await userEvent.click(within(taskNavigation).getByRole("link", { name: "草稿任务" }));
  expect(within(taskNavigation).getByRole("link", { name: "草稿任务" })).toHaveClass("active");
  expect(within(taskNavigation).getByRole("link", { name: "全部任务" })).not.toHaveClass("active");
  expect(screen.getByRole("heading", { name: "草稿任务" })).toBeInTheDocument();
  expect(screen.getByText("查看尚未进入执行流程的草稿任务。")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "待规划" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "整理草稿" })).toHaveAttribute(
    "href",
    "/orgs/org-1/issues/issue-draft",
  );
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/issues?status=backlog",
    expect.objectContaining({ method: "GET" }),
  );

  await userEvent.click(within(taskNavigation).getByRole("link", { name: "空项目" }));
  expect(within(taskNavigation).getByRole("link", { name: "空项目" })).toHaveClass("active");
  expect(within(taskNavigation).getByRole("link", { name: "草稿任务" })).not.toHaveClass("active");
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/issues?projectId=project-empty",
    expect.objectContaining({ method: "GET" }),
  );
  expect(screen.getByRole("heading", { name: "空项目" })).toBeInTheDocument();
  expect(screen.getByText("查看该项目关联的任务，按状态跟进执行进度。")).toBeInTheDocument();
  const emptyMessage = screen.getByText("该项目暂无关联任务。");
  const emptySurface = emptyMessage.closest(".issues-list-surface")!;
  const emptySummary = within(emptySurface as HTMLElement).getByText("总数").closest(".project-issue-status-summary")!;
  expect([...emptySurface.children].indexOf(emptySummary)).toBeLessThan([...emptySurface.children].indexOf(emptyMessage));
});
