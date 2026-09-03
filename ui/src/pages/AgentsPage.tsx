import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Navigate, useParams } from "react-router-dom";
import { agentsApi } from "../api/agents";
import { AgentsWorkspace } from "../components/ContextWorkspace";
import { ErrorNotice } from "../components/ErrorNotice";
import { TertiaryPageHeader } from "../components/TertiaryPageShell";

type EmptyAgentTab = "configuration" | "runs";

export function AgentsPage() {
  const { orgId = "" } = useParams();
  const [activeTab, setActiveTab] = useState<EmptyAgentTab>("configuration");
  const agents = useQuery({ queryKey: ["agents", orgId], queryFn: () => agentsApi.list(orgId) });
  const agentList = Array.isArray(agents.data) ? agents.data : [];

  if (agentList.length > 0) {
    return <Navigate replace to={`/orgs/${orgId}/agents/${agentList[0].id}/configuration`} />;
  }

  return (
    <AgentsWorkspace contentClassName="org-content-full" orgId={orgId}>
      <TertiaryPageHeader eyebrow="Agents" title="智能体" />
      <nav aria-label="智能体详情导航" className="detail-tabs">
        <button className={activeTab === "configuration" ? "active" : ""} onClick={() => setActiveTab("configuration")} type="button">配置</button>
        <button className={activeTab === "runs" ? "active" : ""} onClick={() => setActiveTab("runs")} type="button">运行</button>
      </nav>
      {agents.error && <ErrorNotice error={agents.error} />}
      <section className="panel agent-empty-state">
        <h2>
          {activeTab === "configuration" && "配置"}
          {activeTab === "runs" && "运行"}
        </h2>
        <p className="muted">暂无智能体。创建智能体后可查看和管理此内容。</p>
      </section>
    </AgentsWorkspace>
  );
}
