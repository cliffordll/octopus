import { cleanup, screen, within } from "@testing-library/react";
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
    executionWorkspacePolicy: null,
    resources: [
      {
        id: "attachment-1",
        resourceId: "resource-1",
        role: "working_set",
        note: null,
        resource: { name: "Repository", locator: "D:/coding/octopus" },
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

  await userEvent.clear(screen.getByLabelText("描述"));
  await userEvent.type(screen.getByLabelText("描述"), "更新后的描述");
  await userEvent.selectOptions(screen.getByLabelText("负责人"), "agent-1");
  await userEvent.clear(screen.getByLabelText("目标日期"));
  await userEvent.type(screen.getByLabelText("目标日期"), "2026-06-01");
  await userEvent.type(screen.getByLabelText("目标 ID"), "goal-1,goal-2");
  await userEvent.click(screen.getByRole("button", { name: "保存项目" }));
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
        goalIds: ["goal-1", "goal-2"],
      }),
    }),
  );

  await userEvent.click(within(tabs).getByRole("link", { name: "资源" }));
  expect(await screen.findByText("Repository")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "编辑" }));
  const editResourceForm = screen.getByRole("button", { name: "保存资源" }).closest("form");
  expect(editResourceForm).not.toBeNull();
  await userEvent.selectOptions(within(editResourceForm as HTMLElement).getByLabelText("角色"), "reference");
  await userEvent.type(within(editResourceForm as HTMLElement).getByLabelText("备注"), "主要仓库");
  await userEvent.clear(within(editResourceForm as HTMLElement).getByLabelText("排序"));
  await userEvent.type(within(editResourceForm as HTMLElement).getByLabelText("排序"), "2");
  await userEvent.click(within(editResourceForm as HTMLElement).getByRole("button", { name: "保存资源" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/projects/project-1/resources/attachment-1",
    expect.objectContaining({
      method: "PATCH",
      body: JSON.stringify({ role: "reference", note: "主要仓库", sortOrder: 2 }),
    }),
  );
  await userEvent.type(screen.getByLabelText("资源 ID"), "resource-2");
  await userEvent.type(screen.getByLabelText("排序"), "3");
  await userEvent.click(screen.getByRole("button", { name: "添加资源" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/projects/project-1/resources",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ resourceId: "resource-2", role: "working_set", sortOrder: 3 }),
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
  expect(projectIssueCard).toHaveTextContent("2026-05-28T10:00:00Z");
  expect(projectIssueCard).toHaveTextContent("归属");
  expect(projectIssueCard).toHaveTextContent("Builder");
  const issueSummary = screen.getByText("总数").closest(".project-issue-status-summary");
  expect(issueSummary).not.toBeNull();
  expect(within(issueSummary as HTMLElement).getByText("总数").closest(".summary-metric")).toHaveTextContent("3");
  expect(within(issueSummary as HTMLElement).getByText("活跃").closest(".summary-metric")).toHaveTextContent("2");
  expect(within(issueSummary as HTMLElement).getByText("阻塞").closest(".summary-metric")).toHaveTextContent("1");
  expect(within(issueSummary as HTMLElement).getByText("完成").closest(".summary-metric")).toHaveTextContent("1");
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
});
