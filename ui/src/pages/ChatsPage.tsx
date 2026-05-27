import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { chatsApi } from "../api/chats";
import { Badge } from "../components/Badge";
import { ErrorNotice } from "../components/ErrorNotice";
import { OrgNavigation } from "./OrganizationPage";

export function ChatsPage() {
  const { orgId = "" } = useParams();
  const [title, setTitle] = useState("");
  const [agentId, setAgentId] = useState("");
  const queryClient = useQueryClient();
  const chats = useQuery({ queryKey: ["chats", orgId], queryFn: () => chatsApi.list(orgId) });
  const create = useMutation({
    mutationFn: () => chatsApi.create(orgId, { title: title.trim(), preferredAgentId: agentId.trim() || null }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["chats", orgId] }),
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    if (title.trim()) create.mutate();
  }
  return (
    <>
      <header className="page-header">
        <div><p className="eyebrow">Chats</p><h1>对话</h1></div>
        <OrgNavigation orgId={orgId} />
      </header>
      <div className="grid-two">
        <section className="panel">
          <h2>会话列表</h2>
          {chats.error && <ErrorNotice error={chats.error} />}
          <div className="list">
            {chats.data?.map((chat) => (
              <article className="row" key={chat.id}>
                <Link to={`/orgs/${orgId}/chats/${chat.id}`}>{chat.title}</Link>
                <Badge>{chat.status}</Badge>
              </article>
            ))}
          </div>
        </section>
        <form className="panel form" onSubmit={submit}>
          <h2>创建对话</h2>
          <label>标题<input value={title} onChange={(event) => setTitle(event.target.value)} required /></label>
          <label>首选 Agent ID<input value={agentId} onChange={(event) => setAgentId(event.target.value)} /></label>
          {create.error && <ErrorNotice error={create.error} />}
          <button type="submit">新建对话</button>
        </form>
      </div>
    </>
  );
}
