const icons = {
  messages: <path d="M21 11.5a8.5 8.5 0 0 1-8.5 8.5H4l-3 3V11.5a8.5 8.5 0 0 1 8.5-8.5h3a8.5 8.5 0 0 1 8.5 8.5Z" />,
  agents: <><rect x="4" y="7" width="16" height="14" rx="4" /><path d="M12 3v4M1 12v5m22-5v5M9 12v2m6-2v2m-6 3h6" /></>,
  issues: <><rect x="3" y="3" width="18" height="18" rx="3" /><path d="m7 8 1 1 2-2m-3 8 1 1 2-2m3-6h4m-4 7h4" /></>,
  organization: <><rect x="9" y="2" width="6" height="5" rx="1" /><rect x="2" y="17" width="6" height="5" rx="1" /><rect x="16" y="17" width="6" height="5" rx="1" /><path d="M12 7v5M5 17v-5h14v5" /></>,
  create: <path d="M12 4v16M4 12h16" />,
  settings: <><path d="m10 3-.4 2.4-2 1.2L5.2 6 3 9.8l1.8 1.7v1L3 14.2 5.2 18l2.4-.6 2 1.2L10 21h4l.4-2.4 2-1.2 2.4.6 2.2-3.8-1.8-1.7v-1L21 9.8 18.8 6l-2.4.6-2-1.2L14 3Z" /><circle cx="12" cy="12" r="3" /></>,
};

export function SidebarIcon({ name }: { name: keyof typeof icons }) {
  return (
    <svg aria-hidden="true" focusable="false" className="sidebar-nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round">
      {icons[name]}
    </svg>
  );
}
