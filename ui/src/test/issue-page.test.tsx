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
    workProducts: [
      {
        id: "wp-1",
        orgId: "org-1",
        projectId: "project-1",
        issueId: "issue-1",
        executionWorkspaceId: "exec-1",
        runtimeServiceId: "svc-1",
        type: "pull_request",
        provider: "github",
        externalId: "42",
        title: "登录流程 PR",
        url: "https://example.com/pr/42",
        status: "open",
        reviewState: "pending",
        isPrimary: true,
        healthStatus: "healthy",
        summary: "实现登录流程并等待 review",
        metadata: null,
        createdByRunId: "run-1",
        createdAt: "2026-05-28T09:00:00Z",
        updatedAt: "2026-05-28T10:00:00Z",
      },
    ],
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
    if (path === "/api/issues/issue-1/attachments" && init?.method === "GET") {
      return respond([
        {
          id: "attachment-1",
          orgId: "org-1",
          issueId: "issue-1",
          issueCommentId: null,
          assetId: "asset-1",
          usage: "evidence",
          provider: "local",
          objectKey: "issue/attachments/note.txt",
          contentType: "text/plain",
          byteSize: 12,
          sha256: "abc",
          originalFilename: "note.txt",
          createdAt: "",
          updatedAt: "",
          contentPath: "/api/assets/asset-1/content",
        },
      ]);
    }
    if (path === "/api/orgs/org-1/issues/issue-1/attachments" && init?.method === "POST") {
      return respond({ id: "attachment-2", originalFilename: "upload.txt" }, 201);
    }
    if (path === "/api/attachments/attachment-1" && init?.method === "DELETE") {
      return respond({}, 204);
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
  expect(screen.getByRole("region", { name: "工作产物" })).toHaveTextContent("登录流程 PR");
  expect(screen.getByRole("region", { name: "工作产物" })).toHaveTextContent("pull_request");
  expect(screen.getByRole("link", { name: "打开产物" })).toHaveAttribute("href", "https://example.com/pr/42");
  expect(await screen.findByRole("region", { name: "Attachments" })).toHaveTextContent("note.txt");
  expect(screen.getByRole("link", { name: "下载" })).toHaveAttribute("href", "/api/assets/asset-1/content");
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

  await userEvent.upload(screen.getByLabelText("附件"), new File(["upload"], "upload.txt", { type: "text/plain" }));
  await userEvent.click(screen.getByRole("button", { name: "上传附件" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/issues/issue-1/attachments",
    expect.objectContaining({ method: "POST", body: expect.any(FormData) }),
  );

  await userEvent.click(screen.getByRole("button", { name: "删除" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/attachments/attachment-1",
    expect.objectContaining({ method: "DELETE" }),
  );

  await userEvent.click(screen.getByRole("button", { name: "Approve Review" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/issues/issue-1/review-decision",
    expect.objectContaining({ method: "POST" }),
  );
});
