import { useQuery } from "@tanstack/react-query";
import { Navigate, Outlet, useLocation } from "react-router-dom";
import { authApi, isInteractiveHumanSession } from "../api/access";
import { ErrorNotice } from "./ErrorNotice";

export function HumanSessionGate() {
  const location = useLocation();
  const session = useQuery({
    queryKey: ["auth-session"],
    queryFn: authApi.session,
    staleTime: 5_000,
  });

  if (session.isLoading) {
    return <main className="auth-page"><p className="muted">正在验证登录状态...</p></main>;
  }
  if (session.error) {
    return <main className="auth-page"><section className="auth-card"><ErrorNotice error={session.error} /></section></main>;
  }
  if (!isInteractiveHumanSession(session.data)) {
    const destination = `${location.pathname}${location.search}${location.hash}`;
    return <Navigate replace to={`/login?next=${encodeURIComponent(destination)}`} />;
  }
  return <Outlet />;
}
