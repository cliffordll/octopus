import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { renderApp, respond } from "./render-app";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("shows an approval and submits a board decision", async () => {
  const approval = {
    id: "approval-1",
    orgId: "org-1",
    type: "budget_override_required",
    status: "pending",
    requestedByAgentId: null,
    requestedByUserId: null,
    createdAt: "",
    payload: { amount: 1000 },
    decisionNote: null,
    decidedByUserId: null,
    decidedAt: null,
    updatedAt: "",
  };
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/projects" && init?.method === "GET") return respond([]);
    return respond(approval);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/approvals/approval-1");
  expect(await screen.findByRole("heading", { level: 1, name: /budget_override_required/ })).toBeInTheDocument();
  const messageNavigation = screen.getByRole("navigation", { name: "消息导航" });
  expect(within(messageNavigation).getByRole("link", { name: "审批管理" })).toHaveClass("active");
  expect(screen.queryByRole("navigation", { name: "组织导航" })).not.toBeInTheDocument();
  expect(screen.getByText(/"amount": 1000/)).toBeInTheDocument();

  await userEvent.type(screen.getByLabelText("决策备注"), "额度合理");
  await userEvent.click(screen.getByRole("button", { name: "同意" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/approvals/approval-1/approve",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ decisionNote: "额度合理" }),
    }),
  );
});

it("shows approval management cards and resolves a pending approval", async () => {
  const approvals = [
    {
      id: "approval-1",
      orgId: "org-1",
      type: "chat_operation",
      status: "pending",
      requestedByAgentId: "agent-1",
      requestedByUserId: null,
      createdAt: "2026-05-28T04:00:00.000Z",
    },
  ];
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1/chats" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") return respond([]);
    if (path === "/api/orgs/org-1/approvals" && init?.method === "GET") return respond(approvals);
    if (path === "/api/orgs/org-1/approvals" && init?.method === "POST") {
      return respond({ id: "approval-2", orgId: "org-1", type: "chat_operation", status: "pending", requestedByAgentId: "agent-1", requestedByUserId: null, createdAt: "", payload: {} }, 201);
    }
    if (path === "/api/approvals/approval-1/reject" && init?.method === "POST") {
      return respond({ ...approvals[0], status: "rejected", payload: {}, decisionNote: null });
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/approvals");
  expect(await screen.findByRole("heading", { name: "审批管理" })).toBeInTheDocument();
  expect(await screen.findByText("聊天操作审批")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "创建审批" }));
  const dialog = screen.getByRole("dialog");
  await userEvent.selectOptions(within(dialog).getByLabelText("审批类型"), "chat_operation");
  await userEvent.clear(within(dialog).getByLabelText("Payload JSON"));
  fireEvent.change(within(dialog).getByLabelText("Payload JSON"), { target: { value: '{"action":"test"}' } });
  await userEvent.type(within(dialog).getByLabelText("发起智能体 ID"), "agent-1");
  await userEvent.type(within(dialog).getByLabelText("任务 ID"), "issue-1,issue-2");
  await userEvent.click(within(dialog).getByRole("button", { name: "创建" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs/org-1/approvals",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        type: "chat_operation",
        payload: { action: "test" },
        requestedByAgentId: "agent-1",
        issueIds: ["issue-1", "issue-2"],
      }),
    }),
  );
  expect(screen.getByRole("link", { name: "打开完整审批" })).toHaveAttribute(
    "href",
    "/orgs/org-1/approvals/approval-1",
  );

  await userEvent.click(screen.getByRole("button", { name: "拒绝" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/approvals/approval-1/reject",
    expect.objectContaining({ method: "POST", body: JSON.stringify({}) }),
  );
});
