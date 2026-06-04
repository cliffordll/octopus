import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { renderApp, respond } from "./render-app";

afterEach(() => {
  vi.unstubAllGlobals();
});

it("lists and creates organizations", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs" && init?.method === "GET") {
      return respond([{ id: "org-1", urlKey: "core", name: "核心团队", status: "active" }]);
    }
    if (path === "/api/orgs/org-2/agents" && init?.method === "GET") {
      return respond([]);
    }
    return respond({
      id: "org-2",
      urlKey: "design",
      name: "设计团队",
      status: "active",
      description: null,
      issuePrefix: "DES",
      issueCounter: 0,
      budgetMonthlyCents: 0,
      spentMonthlyCents: 0,
      brandColor: null,
      createdAt: "",
      updatedAt: "",
    });
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/organizations");
  expect(await screen.findByRole("link", { name: "核心团队" })).toBeInTheDocument();

  await userEvent.type(screen.getByLabelText("组织名称"), "设计团队");
  await userEvent.type(screen.getByLabelText("月度预算（美元）"), "2500");
  await userEvent.type(screen.getByLabelText("品牌色"), "#3366ff");
  await userEvent.click(screen.getByLabelText("新建智能体需要审批"));
  await userEvent.selectOptions(screen.getByLabelText("默认聊天任务创建模式"), "auto_create");
  await userEvent.click(screen.getByRole("button", { name: "新建组织" }));

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        name: "设计团队",
        budgetMonthlyCents: 250000,
        brandColor: "#3366ff",
        requireBoardApprovalForNewAgents: true,
        defaultChatIssueCreationMode: "auto_create",
      }),
    }),
  );
  expect(await screen.findByText("首个智能体将作为 CEO 创建")).toBeInTheDocument();
});
