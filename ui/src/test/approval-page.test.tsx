import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { renderApp, respond } from "./render-app";

afterEach(() => {
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
  const fetchMock = vi.fn().mockReturnValue(respond(approval));
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/approvals/approval-1");
  expect(await screen.findByRole("heading", { name: /budget_override_required/ })).toBeInTheDocument();
  expect(screen.getByText(/"amount": 1000/)).toBeInTheDocument();

  await userEvent.type(screen.getByLabelText("决策备注"), "额度合理");
  await userEvent.click(screen.getByRole("button", { name: "批准" }));
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/approvals/approval-1/approve",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ decisionNote: "额度合理" }),
    }),
  );
});
