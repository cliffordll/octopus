import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { accessApi, authApi, isInteractiveHumanSession } from "../api/access";
import { ErrorNotice } from "../components/ErrorNotice";

export function InvitePage() {
  const { token = "" } = useParams();
  const navigate = useNavigate();
  const invite = useQuery({
    enabled: Boolean(token),
    queryKey: ["invite", token],
    queryFn: () => accessApi.inspectInvite(token),
  });
  const session = useQuery({ queryKey: ["auth-session"], queryFn: authApi.session });
  const accept = useMutation({
    mutationFn: () => accessApi.acceptInvite(token),
    onSuccess: (accepted) => navigate(accepted.orgId ? `/orgs/${accepted.orgId}/issues` : "/", { replace: true }),
  });
  const inactive = Boolean(invite.data?.revokedAt || invite.data?.acceptedAt || (invite.data && new Date(invite.data.expiresAt).getTime() <= Date.now()));

  return (
    <main className="auth-page">
      <section className="auth-card" aria-label="接受组织邀请">
        <div>
          <p className="eyebrow">Organization Invite</p>
          <h1>加入组织</h1>
          <p className="muted">此邀请允许 {invite.data?.allowedJoinTypes ?? "..."} 加入 Octopus。</p>
        </div>
        {(invite.error || session.error || accept.error) && <ErrorNotice error={invite.error || session.error || accept.error} />}
        {invite.isLoading || session.isLoading ? (
          <p className="muted">正在验证邀请...</p>
        ) : inactive ? (
          <p>邀请已经接受、撤销或过期，不能再次使用。</p>
        ) : invite.data?.allowedJoinTypes === "agent" ? (
          <p>这是智能体邀请；当前版本尚未开放智能体凭邀请加入的身份引导流程。</p>
        ) : isInteractiveHumanSession(session.data) ? (
          <>
            <div className="access-card">
              <span>
                <strong>{session.data.user.name || session.data.user.email}</strong>
                <small>{session.data.user.email}</small>
              </span>
              <span className="status-pill">当前账户</span>
            </div>
            <button disabled={accept.isPending} onClick={() => accept.mutate()} type="button">
              {accept.isPending ? "正在加入..." : "接受邀请"}
            </button>
          </>
        ) : (
          <Link className="button" to={`/login?next=${encodeURIComponent(`/invite/${token}`)}`}>登录后接受邀请</Link>
        )}
      </section>
    </main>
  );
}
