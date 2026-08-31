const icons = {
  messages: <path d="M21 11.5a8.5 8.5 0 0 1-8.5 8.5H4l-3 3V11.5a8.5 8.5 0 0 1 8.5-8.5h3a8.5 8.5 0 0 1 8.5 8.5Z" />,
  agents: <><rect x="4" y="7" width="16" height="14" rx="4" /><path d="M12 3v4M1 12v5m22-5v5M9 12v2m6-2v2m-6 3h6" /></>,
  issues: <><rect x="3" y="3" width="18" height="18" rx="3" /><path d="m7 8 1 1 2-2m-3 8 1 1 2-2m3-6h4m-4 7h4" /></>,
  organization: <><rect x="9" y="2" width="6" height="5" rx="1" /><rect x="2" y="17" width="6" height="5" rx="1" /><rect x="16" y="17" width="6" height="5" rx="1" /><path d="M12 7v5M5 17v-5h14v5" /></>,
  create: <path d="M12 4v16M4 12h16" />,
  projects: <path d="M3 4h6l2 3h10v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V4Z" />,
  approvals: <><rect x="5" y="4" width="14" height="17" rx="2" /><rect x="9" y="2" width="6" height="4" rx="1" /><path d="m8 13 3 3 5-6" /></>,
  inbox: <><path d="M3 13 6 4h12l3 9v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-6Z" /><path d="M3 13h5l2 3h4l2-3h5" /></>,
  mine: <><circle cx="9" cy="7" r="4" /><path d="M2 21v-3a7 7 0 0 1 12-5m1 5 2 2 5-6" /></>,
  draft: <><path d="M12 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7M14 5l5 5M9 15l1-5L18 2l4 4-8 8Z" /></>,
  following: <path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2-5.6-3-5.6 3L7.5 14 3 9.6l6.2-.9Z" />,
  recent: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
  members: <><circle cx="9" cy="7" r="4" /><path d="M2 21v-3a7 7 0 0 1 14 0v3M17 3a4 4 0 0 1 0 8m2 3a6 6 0 0 1 3 5v2" /></>,
  heartbeat: <path d="M2 12h4l3-8 6 16 3-8h4" />,
  costs: <><circle cx="12" cy="12" r="9" /><path d="M15 8h-4a2 2 0 0 0 0 4h2a2 2 0 0 1 0 4H9m3-10v12" /></>,
  resources: <><path d="m12 2 9 5v10l-9 5-9-5V7l9-5Zm0 10L3 7m9 5 9-5m-9 5v10M7.5 4.5l9 5" /></>,
  workspaces: <><rect x="2" y="3" width="20" height="14" rx="2" /><path d="M8 21h8m-4-4v4M7 7l3 3-3 3m6 0h4" /></>,
  goals: <><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="5" /><circle cx="12" cy="12" r="1" /></>,
  skills: <path d="M3 4h5a5 5 0 0 1 4 2 5 5 0 0 1 4-2h5v15h-5a5 5 0 0 0-4 2 5 5 0 0 0-4-2H3V4Zm9 2v15" />,
  settings: <><path d="m10 3-.4 2.4-2 1.2L5.2 6 3 9.8l1.8 1.7v1L3 14.2 5.2 18l2.4-.6 2 1.2L10 21h4l.4-2.4 2-1.2 2.4.6 2.2-3.8-1.8-1.7v-1L21 9.8 18.8 6l-2.4.6-2-1.2L14 3Z" /><circle cx="12" cy="12" r="3" /></>,
};

export function SidebarIcon({ name }: { name: keyof typeof icons }) {
  return (
    <svg aria-hidden="true" focusable="false" className="sidebar-nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      {icons[name]}
    </svg>
  );
}
