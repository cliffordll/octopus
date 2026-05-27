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
  await userEvent.click(screen.getByRole("button", { name: "新建组织" }));

  expect(fetchMock).toHaveBeenCalledWith(
    "/api/orgs",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ name: "设计团队" }),
    }),
  );
});
