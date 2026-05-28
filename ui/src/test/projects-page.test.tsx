import { cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { renderApp, respond } from "./render-app";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("opens the first project for an organization with projects", async () => {
  const project = { id: "project-1", orgId: "org-1", name: "控制台", status: "planned", urlKey: "console" };
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/projects" && init?.method === "GET") {
      return respond([project]);
    }
    if (path === "/api/projects/project-1" && init?.method === "GET") return respond(project);
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/projects");
  expect(await screen.findByRole("link", { name: "返回项目列表" })).toHaveAttribute(
    "href",
    "/orgs/org-1/projects",
  );
  const organizationNavigation = screen.getByRole("navigation", { name: "组织导航" });
  expect(within(organizationNavigation).getByText("组织")).toBeInTheDocument();
  expect(within(organizationNavigation).getByRole("link", { name: "组织架构" }))
    .toHaveAttribute("href", "/orgs/org-1/structure");
  expect(within(organizationNavigation).getByRole("link", { name: "组织架构" }))
    .toHaveClass("local-nav-primary");
  expect(within(organizationNavigation).getByRole("link", { name: "心跳" }))
    .toHaveAttribute("href", "/orgs/org-1/heartbeat-runs");
  expect(within(organizationNavigation).getByRole("link", { name: "心跳" }))
    .toHaveClass("local-nav-primary");
  expect(within(organizationNavigation).getByText("项目")).toBeInTheDocument();
  expect(within(organizationNavigation).queryByRole("link", { name: "全部项目" })).not.toBeInTheDocument();
  expect(within(organizationNavigation).getByRole("link", { name: "控制台" }))
    .toHaveAttribute("href", "/orgs/org-1/projects/project-1");
  expect(within(organizationNavigation).getByRole("link", { name: "控制台" }))
    .toHaveClass("local-nav-project");
  expect(within(organizationNavigation).getByRole("link", { name: "控制台" }))
    .toHaveClass("local-nav-project-prominent");
  expect(within(organizationNavigation).queryByRole("link", { name: "审批" })).not.toBeInTheDocument();
  expect(within(organizationNavigation).queryByRole("link", { name: "设置" })).not.toBeInTheDocument();
});

it("creates a project from the upstream-style empty state dialog", async () => {
  const createdProject = { id: "project-2", orgId: "org-1", name: "发布流程", status: "planned", urlKey: "release" };
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/projects" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/projects" && init?.method === "POST") return respond(createdProject, 201);
    if (path === "/api/projects/project-2" && init?.method === "GET") return respond(createdProject);
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/projects");
  expect(await screen.findByText("No projects yet.")).toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: "Add Project" }));
  const dialog = within(screen.getByRole("dialog", { name: "Add Project" }));
  await userEvent.type(dialog.getByLabelText("Project Name"), "发布流程");
  await userEvent.selectOptions(dialog.getByLabelText("Project Status"), "planned");
  await userEvent.click(screen.getByRole("button", { name: "Create Project" }));

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/projects",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ name: "发布流程", status: "planned" }),
    }),
  );
});
