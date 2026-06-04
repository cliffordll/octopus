import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { messengerApi } from "../api/messenger";
import { Badge } from "../components/Badge";
import { ChatsWorkspace } from "../components/ContextWorkspace";
import { ErrorNotice } from "../components/ErrorNotice";
import { statusLabel } from "../utils/display";

const SYSTEM_THREADS = [
  { key: "failed-runs", label: "失败运行" },
  { key: "budget-alerts", label: "预算提醒" },
  { key: "join-requests", label: "加入申请" },
];

export function MessengerPage() {
  const { orgId = "" } = useParams();
  const queryClient = useQueryClient();
  const threads = useQuery({ queryKey: ["messenger-threads", orgId], queryFn: () => messengerApi.threads(orgId) });
  const issues = useQuery({ queryKey: ["messenger-issues", orgId], queryFn: () => messengerApi.issues(orgId) });
  const approvals = useQuery({ queryKey: ["messenger-approvals", orgId], queryFn: () => messengerApi.approvals(orgId) });
  const markRead = useMutation({
    mutationFn: (threadKey: string) => messengerApi.read(orgId, threadKey),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["messenger-threads", orgId] });
    },
  });

  return (
    <ChatsWorkspace contentClassName="org-content-full" orgId={orgId}>
      <header className="page-header">
        <div>
          <p className="eyebrow">Messenger</p>
          <h1>消息中心</h1>
        </div>
      </header>
      <section className="panel">
        <h2>线程</h2>
        {threads.error && <ErrorNotice error={threads.error} />}
        <div className="card-grid">
          {threads.data?.map((thread) => (
            <article className="summary-card" key={thread.threadKey}>
              <div className="meta-line">
                <Badge>{statusLabel(thread.kind)}</Badge>
                {thread.needsAttention && <Badge>需关注</Badge>}
                {thread.unreadCount > 0 && <Badge>{thread.unreadCount} 未读</Badge>}
              </div>
              <h3>{thread.title}</h3>
              {thread.subtitle && <p className="muted">{thread.subtitle}</p>}
              {thread.preview && <p>{thread.preview}</p>}
              <div className="button-row">
                {thread.kind === "chat" && thread.threadKey.startsWith("chat:") && (
                  <Link className="button secondary small-button" to={`/orgs/${orgId}/chats/${thread.threadKey.slice(5)}`}>打开对话</Link>
                )}
                <button className="button secondary small-button" onClick={() => markRead.mutate(thread.threadKey)} type="button">
                  标记已读
                </button>
              </div>
            </article>
          ))}
          {threads.isSuccess && threads.data.length === 0 && <p className="muted">暂无消息线程。</p>}
        </div>
      </section>
      <section className="panel">
        <h2>聚合线程</h2>
        <div className="card-grid">
          <ThreadBundleCard title="任务" bundle={issues.data} error={issues.error} />
          <ThreadBundleCard title="审批" bundle={approvals.data} error={approvals.error} />
          {SYSTEM_THREADS.map((thread) => (
            <SystemThreadCard key={thread.key} orgId={orgId} threadKind={thread.key} title={thread.label} />
          ))}
        </div>
      </section>
    </ChatsWorkspace>
  );
}

function ThreadBundleCard({ title, bundle, error }: { title: string; bundle?: Awaited<ReturnType<typeof messengerApi.issues>>; error: unknown }) {
  return (
    <article className="summary-card">
      <h3>{title}</h3>
      {Boolean(error) && <ErrorNotice error={error} />}
      {bundle && (
        <>
          <div className="meta-line">
            <Badge>{bundle.summary.unreadCount} 未读</Badge>
            {bundle.summary.needsAttention && <Badge>需关注</Badge>}
          </div>
          <p>{String(bundle.summary.preview ?? bundle.detail.description ?? "暂无最新消息")}</p>
          <small className="muted">{bundle.detail.items.length} 条记录</small>
        </>
      )}
    </article>
  );
}

function SystemThreadCard({ orgId, threadKind, title }: { orgId: string; threadKind: string; title: string }) {
  const query = useQuery({
    queryKey: ["messenger-system", orgId, threadKind],
    queryFn: () => messengerApi.system(orgId, threadKind),
  });
  return <ThreadBundleCard title={title} bundle={query.data} error={query.error} />;
}
