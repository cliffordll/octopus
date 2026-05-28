import { cleanup, screen, within } from "@testing-library/react";
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
  expect(await screen.findByRole("link", { name: "实现登录流程" })).toHaveAttribute(
    "href",
    "/orgs/org-1/issues/issue-1",
  );
  const issueCard = screen.getByRole("link", { name: "实现登录流程" }).closest(".project-issue-status-row");
  expect(issueCard).not.toBeNull();
  expect(issueCard).toHaveTextContent("创建时间");
  expect(issueCard).toHaveTextContent("2026-05-28T10:00:00Z");
  expect(issueCard).toHaveTextContent("归属");
  expect(issueCard).toHaveTextContent("Builder");
  expect(screen.queryByLabelText("状态筛选")).not.toBeInTheDocument();
  const issueSummary = screen.getByText("Total").closest(".project-issue-status-summary");
  expect(issueSummary).not.toBeNull();
  expect(within(issueSummary as HTMLElement).getByText("Total").closest(".summary-metric")).toHaveTextContent("1");
  expect(within(issueSummary as HTMLElement).getByText("Active").closest(".summary-metric")).toHaveTextContent("1");
  expect(screen.getByRole("heading", { name: "Backlog" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Todo" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "In Progress" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "In Review" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Done" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Blocked" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Cancelled" })).toBeInTheDocument();

  expect(screen.queryByLabelText("任务名称")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "新建任务" }));
  const dialog = within(screen.getByRole("dialog", { name: "新建任务" }));
  await userEvent.type(dialog.getByLabelText("任务名称"), "核对发布说明");
  await userEvent.selectOptions(dialog.getByLabelText("智能体"), "agent-1");
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
  expect(await within(taskNavigation).findByText("任务")).toBeInTheDocument();
  expect(within(taskNavigation).getByRole("link", { name: "全部任务" })).toHaveAttribute("href", "/orgs/org-1/issues");
  expect(within(taskNavigation).getByRole("link", { name: "草稿任务" })).toHaveAttribute(
    "href",
    "/orgs/org-1/issues?status=backlog",
  );
  expect(within(taskNavigation).getByRole("link", { name: "关注中" })).toHaveAttribute(
    "href",
    "/orgs/org-1/issues?view=following",
  );
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

  await userEvent.click(within(taskNavigation).getByRole("link", { name: "草稿任务" }));
  expect(within(taskNavigation).getByRole("link", { name: "草稿任务" })).toHaveClass("active");
  expect(within(taskNavigation).getByRole("link", { name: "全部任务" })).not.toHaveClass("active");
  expect(screen.getByRole("heading", { name: "Backlog" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Todo" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "整理草稿" })).toHaveAttribute(
    "href",
    "/orgs/org-1/issues/issue-draft",
  );
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/issues?status=backlog",
    expect.objectContaining({ method: "GET" }),
  );

  await userEvent.click(within(taskNavigation).getByRole("link", { name: "关注中" }));
  expect(within(taskNavigation).getByRole("link", { name: "关注中" })).toHaveClass("active");
  expect(screen.getByRole("heading", { name: "Backlog" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Blocked" })).toBeInTheDocument();

  await userEvent.click(within(taskNavigation).getByRole("link", { name: "空项目" }));
  expect(within(taskNavigation).getByRole("link", { name: "空项目" })).toHaveClass("active");
  expect(within(taskNavigation).getByRole("link", { name: "草稿任务" })).not.toHaveClass("active");
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/issues?projectId=project-empty",
    expect.objectContaining({ method: "GET" }),
  );
});
