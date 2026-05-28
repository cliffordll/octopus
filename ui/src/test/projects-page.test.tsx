import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { renderApp, respond } from "./render-app";

afterEach(() => {
  vi.unstubAllGlobals();
});

it("lists and creates projects for an organization", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/projects" && init?.method === "GET") {
      return respond([
        { id: "project-1", orgId: "org-1", name: "控制台", status: "planned", urlKey: "console" },
      ]);
    }
    return respond({ id: "project-2", orgId: "org-1", name: "发布流程", status: "backlog" }, 201);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/projects");
  await screen.findAllByRole("link", { name: "控制台" });
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

  await userEvent.type(screen.getByLabelText("Project 名称"), "发布流程");
  await userEvent.selectOptions(screen.getByLabelText("Project 状态"), "planned");
  await userEvent.click(screen.getByRole("button", { name: "新建 Project" }));

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/projects",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ name: "发布流程", status: "planned" }),
    }),
  );
});
