import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { authApi, isInteractiveHumanSession } from "../api/access";
import { AUTH_SESSION_STALE_TIME_MS, replaceAuthenticatedSession } from "../auth/sessionCache";

export function SidebarAccountMenu({ onOpenAccount }: { onOpenAccount: () => void }) {
  const queryClient = useQueryClient();
  const session = useQuery({
    queryKey: ["auth-session"],
    queryFn: authApi.session,
    staleTime: AUTH_SESSION_STALE_TIME_MS,
  });
  const signOut = useMutation({
    mutationFn: authApi.signOut,
    onSuccess: () => {
      replaceAuthenticatedSession(queryClient, null);
    },
  });
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function closeOnOutsideInteraction(event: MouseEvent | FocusEvent) {
      if (event.target instanceof Node && menuRef.current && !menuRef.current.contains(event.target)) {
        setOpen(false);
      }
    }

    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
      }
    }

    document.addEventListener("mousedown", closeOnOutsideInteraction);
    document.addEventListener("focusin", closeOnOutsideInteraction);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("mousedown", closeOnOutsideInteraction);
      document.removeEventListener("focusin", closeOnOutsideInteraction);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, []);

  if (!isInteractiveHumanSession(session.data)) {
    return null;
  }

  const displayName = session.data.user.name || session.data.user.email;
  const sourceLabel = session.data.session?.source === "proxy_token" ? "代理身份" : "本地 Session";

  return (
    <div className="sidebar-account" ref={menuRef}>
      <button
        aria-expanded={open}
        aria-label={`当前用户：${displayName}`}
        className="sidebar-account-trigger"
        onClick={() => setOpen((current) => !current)}
        title={`${displayName} · ${session.data.user.email}`}
        type="button"
      >
        <span aria-hidden="true" className="sidebar-account-avatar">
          {displayName.slice(0, 1).toUpperCase()}
        </span>
        <span className="sidebar-account-name">{displayName}</span>
      </button>
      {open && (
        <div aria-label="账号菜单" className="sidebar-account-menu" role="menu">
          <div className="sidebar-account-identity">
            <span aria-hidden="true" className="access-avatar">
              {displayName.slice(0, 1).toUpperCase()}
            </span>
            <span>
              <strong>{displayName}</strong>
              <small>{session.data.user.email}</small>
            </span>
          </div>
          <span className="status-pill">{sourceLabel}</span>
          <div className="sidebar-account-actions">
            <button
              onClick={() => {
                setOpen(false);
                onOpenAccount();
              }}
              role="menuitem"
              type="button"
            >
              账户设置
            </button>
            <button disabled={signOut.isPending} onClick={() => signOut.mutate()} role="menuitem" type="button">
              退出登录
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
