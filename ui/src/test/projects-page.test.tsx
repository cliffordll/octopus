import { cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { renderApp, respond } from "./render-app";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("opens the first project for an organization with projects", async () => {
  const project = { id: "project-1", orgId: "org-1", name: "控制台", status: "planned", urlKey: "console", color: "#2366b4" };
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/projects" && init?.method === "GET") {
      return respond([project]);
    }
    if (path === "/api/projects/project-1" && init?.method === "GET") return respond(project);
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/projects");
  expect(await screen.findByRole("heading", { name: "控制台", level: 1 })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "返回项目列表" })).not.toBeInTheDocument();
  const organizationNavigation = screen.getByRole("navigation", { name: "组织导航" });
  const organizationSidebar = organizationNavigation.closest("aside")!;
  const sidebarTitle = organizationSidebar.querySelector(":scope > h2");
  expect(sidebarTitle).toHaveTextContent("组织");
  expect(sidebarTitle?.previousElementSibling).toHaveTextContent("Organization");
  expect(sidebarTitle?.nextElementSibling).toBe(organizationNavigation);
  expect(within(organizationNavigation).getByRole("heading", { name: "组织管理" })).toBeInTheDocument();
  expect(within(organizationNavigation).getByRole("link", { name: "组织架构" }))
    .toHaveAttribute("href", "/orgs/org-1/structure");
  expect(within(organizationNavigation).getByRole("link", { name: "组织架构" }))
    .toHaveClass("local-nav-primary");
  expect(within(organizationNavigation).getByRole("link", { name: "心跳" }))
    .toHaveAttribute("href", "/orgs/org-1/heartbeat-runs");
  expect(within(organizationNavigation).getByRole("link", { name: "心跳" }))
    .toHaveClass("local-nav-primary");
  expect(within(organizationNavigation).getByRole("link", { name: "成本" }))
    .toHaveAttribute("href", "/orgs/org-1/costs");
  expect(within(organizationNavigation).getByRole("link", { name: "成本" }))
    .toHaveClass("local-nav-primary");
  expect(within(organizationNavigation).getByText("项目")).toBeInTheDocument();
  expect(within(organizationNavigation).queryByRole("link", { name: "全部项目" })).not.toBeInTheDocument();
  expect(within(organizationNavigation).getByRole("link", { name: "控制台" }))
    .toHaveAttribute("href", "/orgs/org-1/projects/project-1");
  expect(within(organizationNavigation).getByRole("link", { name: "控制台" }))
    .toHaveClass("local-nav-project");
  expect(within(organizationNavigation).getByRole("link", { name: "控制台" }))
    .toHaveClass("local-nav-project-prominent");
  const links = within(organizationNavigation).getAllByRole("link");
  expect(links).toHaveLength(9);
  for (const link of links) {
    expect(link.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    expect(link.querySelector(".context-entry-icon")?.textContent?.trim()).toBe("");
  }
  for (const [name, path] of [["成员", "members"], ["资源", "resources"], ["工作区", "workspaces"], ["目标", "goals"], ["技能", "skills"]]) {
    expect(within(organizationNavigation).getByRole("link", { name, exact: true }))
      .toHaveAttribute("href", `/orgs/org-1/${path}`);
  }
  const projectLink = within(organizationNavigation).getByRole("link", { name: "控制台" });
  expect(projectLink).toHaveClass("active");
  expect(projectLink.querySelector(".project-entry-icon")).toHaveStyle({ background: "#2366b4" });
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
  expect(await screen.findByRole("heading", { name: "暂无项目" })).toBeInTheDocument();

  await userEvent.click(screen.getAllByRole("button", { name: "创建项目" })[0]!);
  const dialog = within(screen.getByRole("dialog", { name: "创建项目" }));
  await userEvent.type(dialog.getByLabelText("项目名称"), "发布流程");
  await userEvent.selectOptions(dialog.getByLabelText("项目状态"), "planned");
  await userEvent.click(dialog.getByRole("button", { name: "创建项目" }));

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/projects",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ name: "发布流程", status: "planned" }),
    }),
  );
});
