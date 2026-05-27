import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, Navigate, useParams } from "react-router-dom";
import { agentsApi } from "../api/agents";
import { AgentsWorkspace } from "../components/ContextWorkspace";
import { ErrorNotice } from "../components/ErrorNotice";

type EmptyAgentTab = "dashboard" | "configuration" | "runs";

export function AgentsPage() {
  const { orgId = "" } = useParams();
  const [activeTab, setActiveTab] = useState<EmptyAgentTab>("dashboard");
  const agents = useQuery({ queryKey: ["agents", orgId], queryFn: () => agentsApi.list(orgId) });
  const agentList = Array.isArray(agents.data) ? agents.data : [];

  if (agentList.length > 0) {
    return <Navigate replace to={`/orgs/${orgId}/agents/${agentList[0].id}/dashboard`} />;
  }

  return (
    <AgentsWorkspace orgId={orgId}>
      <header className="page-header">
        <div><p className="eyebrow">Agents</p><h1>智能体</h1></div>
        <Link className="button" to={`/orgs/${orgId}/agents/new`}>新建智能体</Link>
      </header>
      <nav aria-label="智能体详情导航" className="detail-tabs">
        <button className={activeTab === "dashboard" ? "active" : ""} onClick={() => setActiveTab("dashboard")} type="button">概览</button>
        <button className={activeTab === "configuration" ? "active" : ""} onClick={() => setActiveTab("configuration")} type="button">配置</button>
        <button className={activeTab === "runs" ? "active" : ""} onClick={() => setActiveTab("runs")} type="button">运行</button>
      </nav>
      {agents.error && <ErrorNotice error={agents.error} />}
      <section className="panel agent-empty-state">
        <h2>
          {activeTab === "dashboard" && "概览"}
          {activeTab === "configuration" && "配置"}
          {activeTab === "runs" && "运行"}
        </h2>
        <p className="muted">暂无智能体。创建智能体后可查看和管理此内容。</p>
      </section>
    </AgentsWorkspace>
  );
}
