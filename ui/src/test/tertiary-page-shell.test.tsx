import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  TertiaryPageFrame,
  TertiaryPageHeader,
  TertiaryPageShell,
  TertiaryPageViewport,
} from "../components/TertiaryPageShell";

describe("TertiaryPageFrame", () => {
  it("builds one shared fixed-header and scrolling-content frame", () => {
    const { container } = render(
      <TertiaryPageFrame>
        <TertiaryPageHeader eyebrow="Members" supporting="成员说明" title="成员" />
        <section aria-label="成员内容">内容</section>
      </TertiaryPageFrame>,
    );

    const shell = container.querySelector(".tertiary-page-shell");
    const header = screen.getByRole("heading", { name: "成员" }).closest("header");
    const viewport = screen.getByRole("region", { name: "成员内容" }).parentElement;
    expect(shell).toContainElement(header);
    expect(viewport).toHaveClass("tertiary-page-viewport");
    expect(header?.nextElementSibling).toBe(viewport);
  });

  it("supports a contained body variant", () => {
    const { container } = render(
      <TertiaryPageFrame contained>
        <TertiaryPageHeader eyebrow="Organization" title="架构" />
        <section>画布</section>
      </TertiaryPageFrame>,
    );

    expect(container.querySelector(".tertiary-page-viewport")).toHaveClass("tertiary-page-viewport-contained");
  });

  it("does not double-wrap an existing shell", () => {
    const { container } = render(
      <TertiaryPageFrame>
        <TertiaryPageShell>
          <TertiaryPageHeader eyebrow="Skills" title="技能" />
          <TertiaryPageViewport>内容</TertiaryPageViewport>
        </TertiaryPageShell>
      </TertiaryPageFrame>,
    );

    expect(container.querySelectorAll(".tertiary-page-shell")).toHaveLength(1);
    expect(container.querySelectorAll(".tertiary-page-viewport")).toHaveLength(1);
  });

  it("renders the shared eyebrow, title, supporting, and actions slots", () => {
    const { container } = render(
      <TertiaryPageHeader
        actions={<button type="button">保存</button>}
        eyebrow="Settings"
        supporting="配置说明"
        title="配置"
      />,
    );

    expect(container.querySelector(".tertiary-page-heading .eyebrow")).toHaveTextContent("Settings");
    expect(screen.getByRole("heading", { name: "配置" })).toBeInTheDocument();
    expect(container.querySelector(".tertiary-page-supporting")).toHaveTextContent("配置说明");
    expect(screen.getByRole("button", { name: "保存" }).parentElement).toHaveClass("tertiary-page-actions");
  });
});
