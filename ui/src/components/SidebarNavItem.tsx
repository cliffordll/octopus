import { NavLink } from "react-router-dom";
import { SidebarIcon } from "./SidebarIcon";

const navigationItems = {
  messages: {
    label: "消息",
  },
  agents: {
    label: "智能体",
  },
  issues: {
    label: "任务",
  },
  organization: {
    label: "组织",
  },
};

type SidebarNavItemProps = {
  item: keyof typeof navigationItems;
  to?: string;
  active?: boolean;
};

export function SidebarNavItem({ item, to, active }: SidebarNavItemProps) {
  const { label } = navigationItems[item];
  const content = <SidebarIcon name={item} />;

  if (!to) {
    return <span aria-label={label} aria-disabled="true" role="link" className="nav-disabled sidebar-icon-link" title={label}>{content}</span>;
  }

  return (
    <NavLink
      aria-label={label}
      aria-current={active ? "page" : undefined}
      className={({ isActive }) => `sidebar-icon-link${active || isActive ? " active" : ""}`}
      title={label}
      to={to}
    >
      {content}
    </NavLink>
  );
}
