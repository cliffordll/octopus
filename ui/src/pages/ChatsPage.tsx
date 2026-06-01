import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FocusEvent as ReactFocusEvent, type FormEvent, type KeyboardEvent } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { agentsApi } from "../api/agents";
import { chatsApi } from "../api/chats";
import { projectsApi } from "../api/projects";
import type { ChatMessage } from "../api/types";
import { ChatsWorkspace } from "../components/ContextWorkspace";
import { ErrorNotice } from "../components/ErrorNotice";

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "请求失败";
}

function hasAssistantReply(messages: Array<{ role: string }>) {
  return messages.some((message) => message.role === "assistant");
}

const missingAssistantReplyMessage = "智能体没有返回消息。请检查所选智能体运行配置后重试。";

function skillLabel(entry: Record<string, unknown>) {
  const value = entry.selectionKey ?? entry.key ?? entry.runtimeName ?? entry.name ?? entry.slug ?? entry.id ?? entry.shortName;
  return typeof value === "string" && value.trim() ? value.trim() : "skill";
}

function focusLeftElement(event: ReactFocusEvent<HTMLElement>) {
  return !(event.relatedTarget instanceof Node) || !event.currentTarget.contains(event.relatedTarget);
}

export function ChatsPage() {
  const { orgId = "" } = useParams();
  const [searchParams] = useSearchParams();
  const requestedAgentId = searchParams.get("agentId") ?? "";
  const [agentId, setAgentId] = useState("");
  const [projectId, setProjectId] = useState("");
  const [body, setBody] = useState("");
  const [skillDropdownOpen, setSkillDropdownOpen] = useState(false);
  const skillDropdownRef = useRef<HTMLDetailsElement | null>(null);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const agents = useQuery({ queryKey: ["agents", orgId], queryFn: () => agentsApi.list(orgId) });
  const projects = useQuery({ queryKey: ["projects", orgId], queryFn: () => projectsApi.list(orgId) });
  const selectedAgentSkills = useQuery({
    queryKey: ["agent-skills", agentId],
    queryFn: () => agentsApi.skills(agentId),
    enabled: Boolean(agentId),
  });
  useEffect(() => {
    if (!skillDropdownOpen) return;
    function closeWhenOutside(event: Event) {
      if (event.target instanceof Node && !skillDropdownRef.current?.contains(event.target)) {
        setSkillDropdownOpen(false);
      }
    }
    document.addEventListener("pointerdown", closeWhenOutside);
    document.addEventListener("focusin", closeWhenOutside);
    return () => {
      document.removeEventListener("pointerdown", closeWhenOutside);
      document.removeEventListener("focusin", closeWhenOutside);
    };
  }, [skillDropdownOpen]);
  const agentList = Array.isArray(agents.data) ? agents.data : [];
  const projectList = Array.isArray(projects.data) ? projects.data : [];
  const chatAgentList = agentList.filter((agent) => agent.status !== "terminated");
  const skillEntries = selectedAgentSkills.data && !Array.isArray(selectedAgentSkills.data)
    ? selectedAgentSkills.data.entries
    : [];
  const desiredSkills = selectedAgentSkills.data && !Array.isArray(selectedAgentSkills.data)
    ? selectedAgentSkills.data.desiredSkills
    : [];
  useEffect(() => {
    if (requestedAgentId && chatAgentList.some((agent) => agent.id === requestedAgentId)) {
      setAgentId(requestedAgentId);
    }
  }, [chatAgentList, requestedAgentId]);
  const create = useMutation({
    mutationFn: async () => {
      const draft = body.trim();
      const chat = await chatsApi.create(orgId, {
        title: draft.slice(0, 40) || "新对话",
        preferredAgentId: agentId,
        ...(projectId
          ? { contextLinks: [{ entityType: "project", entityId: projectId }] }
          : {}),
      });
      const optimisticMessage: ChatMessage = {
        id: `pending-${Date.now()}`,
        orgId,
        conversationId: chat.id,
        role: "user",
        kind: "message",
        body: draft,
        status: "completed",
        createdAt: new Date().toISOString(),
      };
      queryClient.setQueryData(["chat", chat.id], chat);
      queryClient.setQueryData(["chat-messages", chat.id], [optimisticMessage]);
      void queryClient.invalidateQueries({ queryKey: ["chats", orgId] });
      try {
        const created = await chatsApi.addMessage(chat.id, { body: draft });
        return {
          chat,
          messages: created.messages,
          firstMessageError: hasAssistantReply(created.messages) ? null : missingAssistantReplyMessage,
        };
      } catch (error) {
        return { chat, messages: [optimisticMessage], firstMessageError: errorMessage(error) };
      }
    },
    onSuccess: ({ chat, messages, firstMessageError }) => {
      queryClient.setQueryData(["chat", chat.id], chat);
      if (messages) {
        queryClient.setQueryData(["chat-messages", chat.id], messages);
        setBody("");
      }
      navigate(`/orgs/${orgId}/chats/${chat.id}`, {
        state: firstMessageError ? { sendError: `首条消息发送失败：${firstMessageError}` } : undefined,
      });
    },
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    if (agentId && body.trim()) {
      create.mutate();
    }
  }
  function handleMessageKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    event.currentTarget.form?.requestSubmit();
  }
  return (
    <ChatsWorkspace contentClassName="org-content-full" orgId={orgId}>
      <header className="page-header">
        <div><p className="eyebrow">Messages</p><h1>新对话</h1></div>
      </header>
      <section className="panel chat-panel">
        <div className="chat-empty-state">
          <h2>What do you want to work on?</h2>
          <p className="muted">选择智能体并发送第一条消息。</p>
        </div>
        <form className="form chat-composer" onSubmit={submit}>
          {agents.isSuccess && chatAgentList.length === 0 && (
            <p className="muted">暂无可用于对话的智能体，请先创建或恢复智能体。</p>
          )}
          <label aria-label="消息输入" className="chat-message-input">
            <textarea
              autoFocus
              aria-label="消息"
              placeholder="输入消息，Enter 发送，Shift+Enter 换行"
              value={body}
              onChange={(event) => setBody(event.target.value)}
              onKeyDown={handleMessageKeyDown}
              required
            />
          </label>
          {agents.error && <ErrorNotice error={agents.error} />}
          {projects.error && <ErrorNotice error={projects.error} />}
          {selectedAgentSkills.error && <ErrorNotice error={selectedAgentSkills.error} />}
          {create.error ? <ErrorNotice error={create.error} /> : null}
          <div className="chat-context-controls">
            <label aria-label="项目选择" className="chat-context-field">
              <select aria-label="项目" value={projectId} onChange={(event) => setProjectId(event.target.value)}>
                <option value="">不关联项目</option>
                {projectList.map((project) => (
                  <option key={project.id} value={project.id}>{project.name}</option>
                ))}
              </select>
            </label>
            <label aria-label="智能体选择" className="chat-context-field">
              <select
                aria-label="对话智能体"
                value={agentId}
                onChange={(event) => setAgentId(event.target.value)}
                required
              >
                <option value="">选择智能体</option>
                {chatAgentList.map((agent) => (
                  <option key={agent.id} value={agent.id}>{agent.name} ({agent.role})</option>
                ))}
              </select>
            </label>
            <details
              className="chat-skill-dropdown"
              onBlur={(event) => {
                if (focusLeftElement(event)) setSkillDropdownOpen(false);
              }}
              onToggle={(event) => setSkillDropdownOpen(event.currentTarget.open)}
              open={skillDropdownOpen}
              ref={skillDropdownRef}
            >
              <summary>技能列表</summary>
              <div className="chat-skill-list">
                {desiredSkills.map((skill) => (
                  <span className="chat-skill-chip active" key={`desired-${skill}`}>{skill}</span>
                ))}
                {skillEntries.map((entry) => (
                  <span className="chat-skill-chip" key={skillLabel(entry)}>{skillLabel(entry)}</span>
                ))}
                {agentId && selectedAgentSkills.isSuccess && desiredSkills.length === 0 && skillEntries.length === 0 && (
                  <span className="muted">暂无技能</span>
                )}
                {!agentId && <span className="muted">选择智能体后查看技能</span>}
              </div>
            </details>
            <button className="chat-create-submit" disabled={chatAgentList.length === 0 || create.isPending} type="submit">
              发送并创建对话
            </button>
          </div>
          <div className="chat-compose-actions">
            <span className="muted">项目和技能作为上下文展示，消息会发送给所选智能体。</span>
          </div>
        </form>
      </section>
    </ChatsWorkspace>
  );
}
