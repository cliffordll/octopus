import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { authApi } from "../api/access";
import { replaceAuthenticatedSession } from "../auth/sessionCache";
import { ErrorNotice } from "../components/ErrorNotice";

export function LoginPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<"sign-in" | "sign-up">("sign-in");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const requestedDestination = new URLSearchParams(location.search).get("next");
  const destination = requestedDestination?.startsWith("/") && !requestedDestination.startsWith("//")
    ? requestedDestination
    : "/";
  const authenticatedDestination = destination.startsWith("/invite/") ? destination : "/";

  const authenticate = useMutation({
    mutationFn: () =>
      mode === "sign-in" ? authApi.signIn(email, password) : authApi.signUp(name, email, password),
    onSuccess: (session) => {
      replaceAuthenticatedSession(queryClient, session);
      navigate(authenticatedDestination, { replace: true });
    },
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    authenticate.mutate();
  }

  return (
    <main className="auth-page">
      <section className="auth-card" aria-label={mode === "sign-in" ? "登录" : "创建账户"}>
        <div>
          <p className="eyebrow">Octopus Access</p>
          <h1>{mode === "sign-in" ? "登录 Octopus" : "创建本地账户"}</h1>
          <p className="muted">使用 Human 账户进入控制面；登录成功后会进入当前账户可访问的组织。</p>
        </div>
        <div className="auth-mode-tabs" role="tablist" aria-label="账户操作">
          <button aria-selected={mode === "sign-in"} className={mode === "sign-in" ? "active" : ""} onClick={() => setMode("sign-in")} role="tab" type="button">
            登录
          </button>
          <button aria-selected={mode === "sign-up"} className={mode === "sign-up" ? "active" : ""} onClick={() => setMode("sign-up")} role="tab" type="button">
            注册
          </button>
        </div>
        <form className="form auth-form" onSubmit={submit}>
          {mode === "sign-up" && (
            <label>
              姓名
              <input autoComplete="name" onChange={(event) => setName(event.target.value)} required value={name} />
            </label>
          )}
          <label>
            邮箱
            <input autoComplete="email" onChange={(event) => setEmail(event.target.value)} required type="email" value={email} />
          </label>
          <label>
            密码
            <input
              autoComplete={mode === "sign-in" ? "current-password" : "new-password"}
              minLength={8}
              onChange={(event) => setPassword(event.target.value)}
              required
              type="password"
              value={password}
            />
          </label>
          {authenticate.error && <ErrorNotice error={authenticate.error} />}
          <button disabled={authenticate.isPending} type="submit">
            {authenticate.isPending ? "处理中..." : mode === "sign-in" ? "登录" : "创建账户"}
          </button>
        </form>
        <Link className="muted auth-back-link" to={destination}>返回控制面</Link>
      </section>
    </main>
  );
}
