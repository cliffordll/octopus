import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { messengerApi } from "../api/messenger";
import type { MessengerThreadBundle, MessengerThreadSummary } from "../api/types";
import { Badge } from "../components/Badge";
import { ChatsWorkspace } from "../components/ContextWorkspace";
import { ErrorNotice } from "../components/ErrorNotice";
import { TertiaryPageHeader } from "../components/TertiaryPageShell";
import { formatDateTime } from "../utils/display";

const SYSTEM_THREADS = ["failed-runs", "budget-alerts", "join-requests"] as const;

type InboxFilter = "all" | "unread" | MessengerThreadSummary["kind"];

interface InboxItem {
  href: string | null;
  id: string;
  kind: MessengerThreadSummary["kind"];
  latestActivityAt: string | null;
  needsAttention: boolean;
  preview: string | null;
  subtitle: string | null;
  threadKey: string;
  title: string;
  unread: boolean;
}

const FILTERS: Array<{ key: InboxFilter; label: string }> = [
  { key: "all", label: "全部" },
  { key: "unread", label: "未读" },
  { key: "chat", label: "对话" },
  { key: "issues", label: "任务" },
  { key: "approvals", label: "审批" },
  { key: "failed-runs", label: "失败运行" },
  { key: "budget-alerts", label: "预算提醒" },
  { key: "join-requests", label: "加入申请" },
];

export function MessengerPage() {
  const { orgId = "" } = useParams();
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<InboxFilter>("all");
  const threads = useQuery({ queryKey: ["messenger-threads", orgId], queryFn: () => messengerApi.threads(orgId) });
  const issues = useQuery({ queryKey: ["messenger-issues", orgId], queryFn: () => messengerApi.issues(orgId) });
  const approvals = useQuery({ queryKey: ["messenger-approvals", orgId], queryFn: () => messengerApi.approvals(orgId) });
  const systemThreads = useQueries({
    queries: SYSTEM_THREADS.map((threadKind) => ({
      queryKey: ["messenger-system", orgId, threadKind],
      queryFn: () => messengerApi.system(orgId, threadKind),
    })),
  });
  const markRead = useMutation({
    mutationFn: (threadKey: string) => messengerApi.read(orgId, threadKey),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["messenger-threads", orgId] });
      void queryClient.invalidateQueries({ queryKey: ["messenger-issues", orgId] });
      void queryClient.invalidateQueries({ queryKey: ["messenger-approvals", orgId] });
      void queryClient.invalidateQueries({ queryKey: ["messenger-system", orgId] });
    },
  });

  const inboxItems = useMemo(() => {
    const chatItems = (threads.data ?? [])
      .filter((thread) => thread.kind === "chat")
      .map((thread): InboxItem => ({
        href: chatHref(orgId, thread),
        id: thread.threadKey,
        kind: thread.kind,
        latestActivityAt: thread.latestActivityAt,
        needsAttention: thread.needsAttention,
        preview: thread.preview,
        subtitle: thread.subtitle,
        threadKey: thread.threadKey,
        title: thread.title,
        unread: thread.unreadCount > 0,
      }));
    const bundleItems = [issues.data, approvals.data, ...systemThreads.map((query) => query.data)]
      .flatMap((bundle) => bundle ? itemsFromBundle(orgId, bundle) : []);
    return [...chatItems, ...bundleItems].sort((left, right) => timestamp(right.latestActivityAt) - timestamp(left.latestActivityAt));
  }, [approvals.data, issues.data, orgId, systemThreads, threads.data]);
  const visibleItems = inboxItems.filter((item) => {
    if (filter === "all") return true;
    if (filter === "unread") return item.unread;
    return item.kind === filter;
  });
  const unreadCount = inboxItems.filter((item) => item.unread).length;
  const isLoading = threads.isLoading || issues.isLoading || approvals.isLoading || systemThreads.some((query) => query.isLoading);

  function markItemRead(item: InboxItem) {
    if (item.unread && !markRead.isPending) markRead.mutate(item.threadKey);
  }

  return (
    <ChatsWorkspace contentClassName="org-content-full" orgId={orgId}>
      <TertiaryPageHeader
        eyebrow="Messenger"
        supporting="集中处理对话、任务、审批和系统提醒。"
        title="消息中心"
      />
      <section className="messenger-inbox">
        <div className="messenger-toolbar">
          <div aria-label="消息筛选" className="messenger-filters" role="group">
            {FILTERS.map((item) => (
              <button
                aria-pressed={filter === item.key}
                className={filter === item.key ? "active" : ""}
                data-kind={item.key === "all" || item.key === "unread" ? undefined : item.key}
                key={item.key}
                onClick={() => setFilter(item.key)}
                type="button"
              >
                {item.label}
                {item.key === "unread" && unreadCount > 0 && <span>{unreadCount}</span>}
              </button>
            ))}
          </div>
          <span className="messenger-total">{visibleItems.length} 条消息</span>
        </div>

        {threads.error && <ErrorNotice error={threads.error} />}
        {issues.error && <ErrorNotice error={issues.error} />}
        {approvals.error && <ErrorNotice error={approvals.error} />}
        {systemThreads.map((query, index) => query.error && <ErrorNotice error={query.error} key={SYSTEM_THREADS[index]} />)}

        <div className="messenger-list">
          <div aria-hidden="true" className="messenger-list-columns">
            <span>消息</span>
            <span>类型</span>
            <span>时间</span>
            <span>状态</span>
          </div>
          {visibleItems.map((item) => (
            <article className={`messenger-list-item${item.unread ? " is-unread" : ""}`} key={`${item.kind}:${item.id}`}>
              <span aria-hidden="true" className="messenger-unread-dot" />
              <div className="messenger-list-content">
                <h2>
                  {item.href ? (
                    <Link className="messenger-row-link" onClick={() => markItemRead(item)} to={item.href}>{item.title}</Link>
                  ) : item.title}
                </h2>
                {(item.preview || item.subtitle) && <p>{item.preview ?? item.subtitle}</p>}
              </div>
              <span className="messenger-kind" data-kind={item.kind}>{kindLabel(item.kind)}</span>
              <time dateTime={item.latestActivityAt ?? undefined}>{formatDateTime(item.latestActivityAt)}</time>
              <div className="messenger-row-status">
                {item.needsAttention && <Badge>需关注</Badge>}
                <Badge>{item.unread ? "未读" : "已读"}</Badge>
                {item.unread && (
                  <button
                    className="messenger-read-action"
                    disabled={markRead.isPending}
                    onClick={() => markItemRead(item)}
                    type="button"
                  >
                    标记已读
                  </button>
                )}
              </div>
            </article>
          ))}
          {isLoading && <p className="messenger-empty muted">正在加载消息...</p>}
          {!isLoading && visibleItems.length === 0 && (
            <p className="messenger-empty muted">{filter === "unread" ? "没有未读消息。" : "当前筛选下没有消息。"}</p>
          )}
        </div>
      </section>
    </ChatsWorkspace>
  );
}

function itemsFromBundle(orgId: string, bundle: MessengerThreadBundle): InboxItem[] {
  return bundle.detail.items.map((value, index) => {
    const id = textValue(value, "id") ?? `${bundle.summary.threadKey}-${index}`;
    const latestActivityAt = textValue(value, "latestActivityAt");
    const unread = isUnread(latestActivityAt, bundle.summary.lastReadAt);
    return {
      href: itemHref(orgId, bundle.summary.kind, value),
      id,
      kind: bundle.summary.kind,
      latestActivityAt,
      needsAttention: unread,
      preview: textValue(value, "preview") ?? textValue(value, "body"),
      subtitle: textValue(value, "subtitle"),
      threadKey: bundle.summary.threadKey,
      title: textValue(value, "title") ?? bundle.summary.title,
      unread,
    };
  });
}

function chatHref(orgId: string, thread: MessengerThreadSummary): string | null {
  if (!thread.threadKey.startsWith("chat:")) return null;
  return `/orgs/${orgId}/chats/${thread.threadKey.slice(5)}`;
}

function itemHref(orgId: string, kind: MessengerThreadSummary["kind"], item: Record<string, unknown>): string | null {
  if (kind === "approvals") {
    const approval = recordValue(item.approval);
    const approvalId = textValue(approval, "id");
    return approvalId ? `/orgs/${orgId}/approvals/${approvalId}` : null;
  }
  const href = textValue(item, "href");
  if (kind === "issues" && href?.startsWith("/issues/")) return `/orgs/${orgId}${href}`;
  return null;
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function textValue(record: Record<string, unknown> | null, key: string): string | null {
  const value = record?.[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function isUnread(latestActivityAt: string | null, lastReadAt: string | null): boolean {
  if (!latestActivityAt) return false;
  if (!lastReadAt) return true;
  return timestamp(latestActivityAt) > timestamp(lastReadAt);
}

function timestamp(value: string | null): number {
  if (!value) return 0;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function kindLabel(kind: MessengerThreadSummary["kind"]): string {
  return {
    approvals: "审批",
    "budget-alerts": "预算提醒",
    chat: "对话",
    "failed-runs": "失败运行",
    issues: "任务",
    "join-requests": "加入申请",
  }[kind];
}
