import { cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { renderApp, respond } from "./render-app";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const goal = {
  id: "goal-1",
  orgId: "org-1",
  title: "交付控制面",
  description: "保持兼容",
  level: "organization",
  status: "active",
  parentId: null,
  ownerAgentId: "agent-1",
  createdAt: "",
  updatedAt: "",
};

function stubGoalFetch() {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/goals" && init?.method === "GET") return respond([goal]);
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") {
      return respond([{ id: "agent-1", name: "Builder", role: "engineer", status: "idle" }]);
    }
    if (path === "/api/orgs/org-1/projects" && init?.method === "GET") {
      return respond([{ id: "project-1", orgId: "org-1", name: "控制台", status: "planned", goalId: "goal-1" }]);
    }
    if (path === "/api/orgs/org-1/issues?goalId=goal-1" && init?.method === "GET") return respond([]);
    if (path === "/api/goals/goal-1" && init?.method === "GET") return respond(goal);
    if (path === "/api/goals/goal-1/dependencies" && init?.method === "GET") {
      return respond({
        goalId: "goal-1",
        blockers: ["linked_projects"],
        isLastRootOrganizationGoal: false,
        counts: {
          childGoals: 0,
          linkedProjects: 1,
          linkedIssues: 0,
          automations: 0,
          costEvents: 0,
          financeEvents: 0,
        },
        previews: {
          childGoals: [],
          linkedProjects: [{ id: "project-1", title: "控制台" }],
          linkedIssues: [],
          automations: [],
        },
      });
    }
    return respond(goal, init?.method === "POST" ? 201 : 200);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

it("lists goals and creates a goal from a dialog", async () => {
  const fetchMock = stubGoalFetch();

  renderApp("/orgs/org-1/goals");
  const organizationNavigation = screen.getByRole("navigation", { name: "组织导航" });
  expect(await within(organizationNavigation).findByRole("link", { name: "目标" })).toHaveAttribute(
    "href",
    "/orgs/org-1/goals",
  );
  expect(within(organizationNavigation).getAllByRole("link", { name: "目标" })).toHaveLength(1);
  expect(await screen.findByRole("link", { name: /交付控制面/ })).toHaveAttribute(
    "href",
    "/orgs/org-1/goals/goal-1",
  );

  expect(screen.queryByRole("dialog", { name: "New Goal" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "New Goal" }));
  const dialog = within(screen.getByRole("dialog", { name: "New Goal" }));
  await userEvent.type(dialog.getByLabelText("Goal title"), "兼容目标");
  await userEvent.selectOptions(dialog.getByLabelText("Level"), "team");
  await userEvent.selectOptions(dialog.getByLabelText("Status"), "planned");
  await userEvent.selectOptions(dialog.getByLabelText("Owner"), "agent-1");
  await userEvent.click(dialog.getByRole("button", { name: "Create goal" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/goals",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        title: "兼容目标",
        level: "team",
        status: "planned",
        ownerAgentId: "agent-1",
      }),
    }),
  );
});

it("shows upstream-style goal detail tabs and configuration", async () => {
  const fetchMock = stubGoalFetch();

  renderApp("/orgs/org-1/goals/goal-1");
  expect(await screen.findByRole("heading", { name: "交付控制面" })).toBeInTheDocument();
  const tabs = screen.getByRole("navigation", { name: "目标详情导航" });
  expect(within(tabs).getByRole("link", { name: "Work (1)" })).toHaveAttribute(
    "href",
    "/orgs/org-1/goals/goal-1/work",
  );
  expect(within(tabs).getByRole("link", { name: "Sub-Goals (0)" })).toHaveAttribute(
    "href",
    "/orgs/org-1/goals/goal-1/children",
  );
  const projectLinks = await screen.findAllByRole("link", { name: "控制台" });
  expect(projectLinks.some((link) => link.getAttribute("href") === "/orgs/org-1/projects/project-1")).toBe(true);
  expect(projectLinks[0]).toHaveAttribute(
    "href",
    "/orgs/org-1/projects/project-1",
  );
  await userEvent.click(within(tabs).getByRole("link", { name: "Activity" }));
  expect(await screen.findByText("Blockers: linked_projects")).toBeInTheDocument();
  await userEvent.click(within(screen.getByRole("navigation", { name: "目标详情导航" })).getByRole("link", { name: "Configuration" }));
  await userEvent.clear(screen.getByLabelText("Description"));
  await userEvent.type(screen.getByLabelText("Description"), "更新目标");
  await userEvent.click(screen.getByRole("button", { name: "Save goal" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/goals/goal-1",
    expect.objectContaining({ method: "PATCH" }),
  );
});
