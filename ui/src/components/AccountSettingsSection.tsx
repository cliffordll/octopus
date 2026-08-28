import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { authApi, isInteractiveHumanSession } from "../api/access";
import { replaceAuthenticatedSession } from "../auth/sessionCache";
import { ErrorNotice } from "./ErrorNotice";

export function AccountSettingsSection() {
  const queryClient = useQueryClient();
  const session = useQuery({ queryKey: ["auth-session"], queryFn: authApi.session });
  const signOut = useMutation({
    mutationFn: authApi.signOut,
    onSuccess: () => {
      replaceAuthenticatedSession(queryClient, null);
    },
  });

  return (
    <section className="settings-empty-section" aria-label="账户">
      <div className="settings-section-heading-copy">
        <p className="eyebrow">Human Account</p>
        <div className="runtime-provider-title-line">
          <h3>账户</h3>
          <p className="muted">查看当前 Human 身份和本地 Session。</p>
        </div>
      </div>
      {session.error && <ErrorNotice error={session.error} />}
      <div className="access-card">
        {session.isLoading ? (
          <p className="muted">正在读取登录状态...</p>
        ) : isInteractiveHumanSession(session.data) ? (
          <>
            <div className="access-identity">
              <span className="access-avatar">{(session.data.user.name || session.data.user.email).slice(0, 1).toUpperCase()}</span>
              <span>
                <strong>{session.data.user.name || session.data.user.email}</strong>
                <small>{session.data.user.email}</small>
              </span>
            </div>
            <div className="access-actions">
              <span className="status-pill">{session.data.session?.source === "proxy_token" ? "代理身份" : "本地 Session"}</span>
              <button className="secondary" disabled={signOut.isPending} onClick={() => signOut.mutate()} type="button">
                退出登录
              </button>
            </div>
          </>
        ) : (
          <>
            <div>
              <strong>当前没有 Human Session</strong>
              <p className="muted">本地可信模式仍可正常使用；需要个人身份时再登录。</p>
            </div>
            <Link className="button" to="/login">登录或注册</Link>
          </>
        )}
      </div>
    </section>
  );
}
