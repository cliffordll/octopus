import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent, type KeyboardEvent } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { agentsApi } from "../api/agents";
import { chatsApi } from "../api/chats";
import { organizationsApi } from "../api/organizations";
import { projectsApi } from "../api/projects";
import type { ChatMessage } from "../api/types";
import { ChatComposerContextBar } from "../components/ChatComposerContextBar";
import { ChatsWorkspace } from "../components/ContextWorkspace";
import { ErrorNotice } from "../components/ErrorNotice";
import { TertiaryPageHeader, TertiaryPageShell, TertiaryPageViewport } from "../components/TertiaryPageShell";
import { roleLabel } from "../utils/display";

function skillLabel(entry: Record<string, unknown>) {
  const value = entry.selectionKey ?? entry.key ?? entry.runtimeName ?? entry.name ?? entry.slug ?? entry.id ?? entry.shortName;
  return typeof value === "string" && value.trim() ? value.trim() : "skill";
}

export function ChatsPage() {
  const { orgId = "" } = useParams();
  const [searchParams] = useSearchParams();
  const requestedAgentId = searchParams.get("agentId") ?? "";
  const [agentId, setAgentId] = useState("");
  const [issueCreationMode, setIssueCreationMode] = useState<"manual_approval" | "auto_create">("manual_approval");
  const [planMode, setPlanMode] = useState(false);
  const [projectId, setProjectId] = useState("");
  const [body, setBody] = useState("");
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const agents = useQuery({ queryKey: ["agents", orgId], queryFn: () => agentsApi.list(orgId) });
  const organization = useQuery({ queryKey: ["organization", orgId], queryFn: () => organizationsApi.get(orgId) });
  const projects = useQuery({ queryKey: ["projects", orgId], queryFn: () => projectsApi.list(orgId) });
  const selectedAgentSkills = useQuery({
    queryKey: ["agent-skills", agentId],
    queryFn: () => agentsApi.skills(agentId),
    enabled: Boolean(agentId),
  });
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
  useEffect(() => {
    const mode = organization.data?.defaultChatIssueCreationMode;
    if (mode === "manual_approval" || mode === "auto_create") {
      setIssueCreationMode(mode);
    }
  }, [organization.data?.defaultChatIssueCreationMode]);
  const create = useMutation({
    mutationFn: async () => {
      const draft = body.trim();
      const chat = await chatsApi.create(orgId, {
        title: draft.slice(0, 40) || "新对话",
        issueCreationMode,
        ...(planMode ? { planMode: true } : {}),
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
      return { chat, initialMessage: draft };
    },
    onSuccess: ({ chat, initialMessage }) => {
      queryClient.setQueryData(["chat", chat.id], chat);
      setBody("");
      navigate(`/orgs/${orgId}/chats/${chat.id}`, {
        state: { initialMessage },
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
      <TertiaryPageShell className="chat-panel">
        <TertiaryPageHeader eyebrow="New chat" supporting="选择智能体并发送第一条消息。" title="新对话" />
        <TertiaryPageViewport className="chat-panel-content tertiary-page-viewport-contained">
          <div className="chat-empty-state">
            <h2>你想让智能体处理什么？</h2>
          </div>
          <form className="form chat-composer" onSubmit={submit}>
          {agents.isSuccess && chatAgentList.length === 0 && (
            <p className="muted">暂无可用于对话的智能体，请先创建或恢复智能体。</p>
          )}
          <label className="chat-message-input">
            <textarea
              autoFocus
              aria-label="消息输入"
              placeholder="输入消息，Enter 发送，Shift+Enter 换行"
              value={body}
              onChange={(event) => setBody(event.target.value)}
              onKeyDown={handleMessageKeyDown}
              required
            />
          </label>
          {agents.error && <ErrorNotice error={agents.error} />}
          {organization.error && <ErrorNotice error={organization.error} />}
          {projects.error && <ErrorNotice error={projects.error} />}
          {selectedAgentSkills.error && <ErrorNotice error={selectedAgentSkills.error} />}
          {create.error ? <ErrorNotice error={create.error} /> : null}
          <ChatComposerContextBar
            agentControl={(
              <select
                aria-label="对话智能体"
                value={agentId}
                onChange={(event) => setAgentId(event.target.value)}
                required
              >
                <option value="">选择智能体</option>
                {chatAgentList.map((agent) => (
                  <option key={agent.id} value={agent.id}>{agent.name} ({roleLabel(agent.role)})</option>
                ))}
              </select>
            )}
            issueCreationModeControl={(
              <select
                aria-label="任务创建模式"
                value={issueCreationMode}
                onChange={(event) => setIssueCreationMode(event.target.value as "manual_approval" | "auto_create")}
              >
                <option value="manual_approval">手动审批</option>
                <option value="auto_create">自动创建</option>
              </select>
            )}
            planMode={{ checked: planMode, onChange: setPlanMode }}
            projectControl={(
              <select aria-label="项目" value={projectId} onChange={(event) => setProjectId(event.target.value)}>
                <option value="">不关联项目</option>
                {projectList.map((project) => (
                  <option key={project.id} value={project.id}>{project.name}</option>
                ))}
              </select>
            )}
            skills={[
              ...desiredSkills.map((label) => ({ active: true, label })),
              ...skillEntries.map((entry) => ({ label: skillLabel(entry) })),
            ]}
            skillsEmptyText={agentId && selectedAgentSkills.isSuccess ? "暂无技能" : "选择智能体后查看技能"}
            submitAriaLabel="发送并创建对话"
            submitDisabled={chatAgentList.length === 0 || create.isPending}
            submitLabel="发送"
          />
          </form>
        </TertiaryPageViewport>
      </TertiaryPageShell>
    </ChatsWorkspace>
  );
}
