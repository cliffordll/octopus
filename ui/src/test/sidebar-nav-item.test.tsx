import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it } from "vitest";
import { SidebarNavItem } from "../components/SidebarNavItem";

afterEach(cleanup);

it.each([
  ["messages", "消息"],
  ["agents", "智能体"],
  ["issues", "任务"],
  ["organization", "组织"],
] as const)("renders %s as an accessible icon link with a Chinese tooltip", (item, label) => {
  render(<MemoryRouter><SidebarNavItem item={item} to="/target" /></MemoryRouter>);
  const link = screen.getByRole("link", { name: label });
  expect(link).toHaveAttribute("title", label);
  expect(link).toHaveAttribute("href", "/target");
  expect(link.textContent).toBe("");
  expect(link.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  expect(link).not.toHaveClass("active");
});

it("supports keyboard navigation and highlights a nested route", async () => {
  render(<MemoryRouter initialEntries={["/agents/agent-1"]}><SidebarNavItem item="agents" to="/agents" /></MemoryRouter>);
  const link = screen.getByRole("link", { name: "智能体" });
  expect(link).toHaveClass("active");
  expect(link).toHaveAttribute("aria-current", "page");
  await userEvent.tab();
  expect(link).toHaveFocus();
});

it("highlights a related section without changing the link destination", () => {
  render(<MemoryRouter initialEntries={["/members"]}><SidebarNavItem item="organization" to="/structure" active /></MemoryRouter>);
  const link = screen.getByRole("link", { name: "组织" });
  expect(link).toHaveClass("active");
  expect(link).toHaveAttribute("href", "/structure");
});

it("keeps an unavailable organization entry disabled", () => {
  render(<SidebarNavItem item="issues" />);
  const link = screen.getByRole("link", { name: "任务" });
  expect(link).toHaveAttribute("aria-disabled", "true");
  expect(link).not.toHaveAttribute("href");
  expect(link).toHaveAttribute("title", "任务");
});
