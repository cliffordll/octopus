import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { renderApp, respond } from "./render-app";

afterEach(() => {
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
    targetDate: null,
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
    updatedAt: "",
  };
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/projects/project-1" && init?.method === "GET") return respond(project);
    if (path === "/api/orgs/org-1/projects" && init?.method === "GET") return respond([project]);
    if (path.endsWith("/resources") && init?.method === "GET") return respond(project.resources);
    if (path === "/api/orgs/org-1/issues?projectId=project-1" && init?.method === "GET") {
      return respond([{
        id: "issue-1",
        orgId: "org-1",
        identifier: "OCT-1",
        title: "完成控制台导航",
        status: "in_progress",
        priority: "high",
        projectId: "project-1",
      }]);
    }
    return respond(project);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/projects/project-1");
  expect(await screen.findByRole("heading", { name: "控制台" })).toBeInTheDocument();
  const tabs = screen.getByRole("navigation", { name: "项目详情导航" });
  expect(within(tabs).getByRole("link", { name: "Configuration" })).toHaveAttribute(
    "href",
    "/orgs/org-1/projects/project-1/configuration",
  );
  expect(within(tabs).getByRole("link", { name: "Resources" })).toHaveAttribute(
    "href",
    "/orgs/org-1/projects/project-1/resources",
  );
  expect(within(tabs).getByRole("link", { name: "Issues" })).toHaveAttribute(
    "href",
    "/orgs/org-1/projects/project-1/issues",
  );

  await userEvent.clear(screen.getByLabelText("描述"));
  await userEvent.type(screen.getByLabelText("描述"), "更新后的描述");
  await userEvent.click(screen.getByRole("button", { name: "保存 Project" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/projects/project-1",
    expect.objectContaining({ method: "PATCH" }),
  );

  await userEvent.click(within(tabs).getByRole("link", { name: "Resources" }));
  expect(await screen.findByText("Repository")).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("Resource ID"), "resource-2");
  await userEvent.click(screen.getByRole("button", { name: "添加 Resource" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/projects/project-1/resources",
    expect.objectContaining({ method: "POST" }),
  );

  await userEvent.click(within(screen.getByRole("navigation", { name: "项目详情导航" })).getByRole("link", { name: "Issues" }));
  expect(await screen.findByRole("link", { name: "完成控制台导航" })).toHaveAttribute(
    "href",
    "/orgs/org-1/issues/issue-1",
  );
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/issues?projectId=project-1",
    expect.objectContaining({ method: "GET" }),
  );
});
