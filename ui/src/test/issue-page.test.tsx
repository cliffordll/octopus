import { cleanup, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { renderApp, respond } from "./render-app";

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.unstubAllGlobals();
});

it("shows an issue and records comments and review decisions", async () => {
  const issue = {
    id: "issue-1",
    orgId: "org-1",
    identifier: "OCT-1",
    title: "实现登录流程",
    description: "接入页面",
    status: "in_review",
    priority: "high",
    projectId: null,
    goalId: null,
    parentId: null,
    assigneeAgentId: null,
    assigneeUserId: null,
    reviewerAgentId: null,
    reviewerUserId: null,
    originKind: "manual",
    originId: null,
    issueNumber: 1,
    requestDepth: 0,
    startedAt: null,
    completedAt: null,
    createdAt: "",
    updatedAt: "",
  };
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/issues" && init?.method === "GET") {
      return respond([issue]);
    }
    if (path === "/api/orgs/org-1/projects" && init?.method === "GET") {
      return respond([]);
    }
    if (path === "/api/issues/issue-1/comments" && init?.method === "GET") {
      return respond([{ id: "c-1", issueId: "issue-1", body: "已有讨论" }]);
    }
    return respond(issue);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/issues/issue-1");
  expect(await screen.findByRole("heading", { name: "实现登录流程" })).toBeInTheDocument();
  const properties = screen.getByRole("region", { name: "Issue properties" });
  expect(properties).toHaveTextContent("Properties");
  expect(properties).toHaveTextContent("Number");
  expect(properties).toHaveTextContent("Depth");
  expect(properties).toHaveTextContent("Started");
  expect(properties).toHaveTextContent("Completed");
  expect(await screen.findByText("已有讨论")).toBeInTheDocument();
  expect(JSON.parse(localStorage.getItem("octopus:recent-issues:org-1") ?? "[]")).toEqual([
    { id: "issue-1", title: "实现登录流程", identifier: "OCT-1", status: "in_review" },
  ]);

  await userEvent.type(screen.getByLabelText("添加评论"), "准备合并");
  await userEvent.click(screen.getByRole("button", { name: "发送评论" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/issues/issue-1/comments",
    expect.objectContaining({ method: "POST" }),
  );

  await userEvent.click(screen.getByRole("button", { name: "批准 Review" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/issues/issue-1/review-decision",
    expect.objectContaining({ method: "POST" }),
  );
});
