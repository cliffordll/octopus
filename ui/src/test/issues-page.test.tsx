import { cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { renderApp, respond } from "./render-app";

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.unstubAllGlobals();
});

it("filters and creates issues for an organization", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
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
          assigneeAgentId: null,
          assigneeUserId: null,
          originKind: "manual",
          originId: null,
          updatedAt: "",
        },
      ]);
    }
    return respond({ id: "issue-2" });
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/issues");
  expect(await screen.findByRole("link", { name: "实现登录流程" })).toHaveAttribute(
    "href",
    "/orgs/org-1/issues/issue-1",
  );

  await userEvent.selectOptions(screen.getByLabelText("状态筛选"), "in_review");
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/issues?status=in_review",
    expect.objectContaining({ method: "GET" }),
  );

  await userEvent.type(screen.getByLabelText("Issue 标题"), "核对发布说明");
  await userEvent.click(screen.getByRole("button", { name: "新建 Issue" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/issues",
    expect.objectContaining({ method: "POST" }),
  );
});

it("groups task navigation by task shortcuts, recent views, and project issues", async () => {
  localStorage.setItem(
    "octopus:recent-issues:org-1",
    JSON.stringify([{ id: "issue-recent", title: "最近处理", identifier: "OCT-9", status: "todo" }]),
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
          assigneeAgentId: null,
          assigneeUserId: null,
          originKind: "manual",
          originId: null,
          updatedAt: "",
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
  expect(within(taskNavigation).getByRole("link", { name: /最近处理/ })).toHaveAttribute(
    "href",
    "/orgs/org-1/issues/issue-recent",
  );
  expect(within(taskNavigation).getByText("项目")).toBeInTheDocument();
  expect(await within(taskNavigation).findByRole("link", { name: "控制台" })).toHaveAttribute(
    "href",
    "/orgs/org-1/issues?projectId=project-1",
  );
  expect(within(taskNavigation).getByRole("link", { name: /实现登录流程/ })).toHaveAttribute(
    "href",
    "/orgs/org-1/issues/issue-1",
  );
  expect(taskNavigation).toHaveTextContent("in_progress");
  expect(within(taskNavigation).getByRole("link", { name: "增长" })).toHaveAttribute(
    "href",
    "/orgs/org-1/issues?projectId=project-2",
  );
  expect(within(taskNavigation).getByRole("link", { name: /设计增长实验/ })).toBeInTheDocument();
  expect(taskNavigation).toHaveTextContent("blocked");
  expect(within(taskNavigation).getByRole("link", { name: "空项目" })).toHaveAttribute(
    "href",
    "/orgs/org-1/issues?projectId=project-empty",
  );
  expect(taskNavigation).not.toHaveTextContent("暂无任务");

  await userEvent.click(within(taskNavigation).getByRole("link", { name: "草稿任务" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/issues?status=backlog",
    expect.objectContaining({ method: "GET" }),
  );

  await userEvent.click(within(taskNavigation).getByRole("link", { name: "空项目" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/issues?projectId=project-empty",
    expect.objectContaining({ method: "GET" }),
  );
});
