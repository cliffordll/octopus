import { cleanup, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderApp, respond } from "./render-app";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("shows current reporting relationships in the organization structure", async () => {
  const agents = [
    { id: "agent-ceo", name: "Founder", role: "ceo", status: "idle", reportsTo: null },
    { id: "agent-1", name: "Builder", role: "engineer", status: "active", reportsTo: "agent-ceo" },
  ];
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs" && init?.method === "GET") {
      return respond([{ id: "org-1", name: "核心团队", status: "active" }]);
    }
    if (path === "/api/orgs/org-1/agents" && init?.method === "GET") return respond(agents);
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/structure");

  expect(await screen.findByRole("heading", { name: "组织架构" })).toBeInTheDocument();
  expect(await screen.findByText("Builder")).toBeInTheDocument();
  expect(await screen.findByText("向 Founder 汇报")).toBeInTheDocument();
});

it("routes an organization root to the empty structure state", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-empty/agents" && init?.method === "GET") return respond([]);
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-empty");

  expect(await screen.findByText("暂无智能体。创建首个智能体以建立组织架构。")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "新建智能体" })).toHaveAttribute(
    "href",
    "/orgs/org-empty/agents/new",
  );
});

it("loads organization settings from the avatar destination route", async () => {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    if (path === "/api/orgs/org-1" && init?.method === "GET") {
      return respond({ id: "org-1", name: "核心团队", description: "核心组织" });
    }
    return respond([]);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderApp("/orgs/org-1/settings");

  expect(await screen.findByDisplayValue("核心团队")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "保存组织" })).toBeInTheDocument();
  expect(screen.queryByRole("navigation", { name: "组织导航" })).not.toBeInTheDocument();
});
