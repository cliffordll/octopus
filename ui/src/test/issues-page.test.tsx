import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { renderApp, respond } from "./render-app";

afterEach(() => {
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
  expect(
    await within(screen.getByRole("navigation", { name: "任务导航" })).findByRole("link", {
      name: /实现登录流程/,
    }),
  ).toHaveAttribute("href", "/orgs/org-1/issues/issue-1");

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
