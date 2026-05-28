import { Route, Routes } from "react-router-dom";
import { AppShell } from "../components/AppShell";
import { ApprovalPage } from "../pages/ApprovalPage";
import { ApprovalsPage } from "../pages/ApprovalsPage";
import { AgentPage } from "../pages/AgentPage";
import { AgentsPage } from "../pages/AgentsPage";
import { NewAgentPage } from "../pages/NewAgentPage";
import { ChatPage } from "../pages/ChatPage";
import { ChatsPage } from "../pages/ChatsPage";
import { GoalPage } from "../pages/GoalPage";
import { GoalsPage } from "../pages/GoalsPage";
import { HomePage } from "../pages/HomePage";
import { HeartbeatRunsPage } from "../pages/HeartbeatRunsPage";
import { IssuePage } from "../pages/IssuePage";
import { IssuesPage } from "../pages/IssuesPage";
import { OrganizationIndexPage, OrganizationPage, OrganizationStructurePage } from "../pages/OrganizationPage";
import { OrganizationsPage } from "../pages/OrganizationsPage";
import { ProjectPage } from "../pages/ProjectPage";
import { ProjectsPage } from "../pages/ProjectsPage";

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<HomePage />} />
        <Route path="organizations" element={<OrganizationsPage />} />
        <Route path="orgs/:orgId" element={<OrganizationIndexPage />} />
        <Route path="orgs/:orgId/structure" element={<OrganizationStructurePage />} />
        <Route path="orgs/:orgId/settings" element={<OrganizationPage />} />
        <Route path="orgs/:orgId/heartbeat-runs" element={<HeartbeatRunsPage />} />
        <Route path="orgs/:orgId/goals" element={<GoalsPage />} />
        <Route path="orgs/:orgId/goals/:goalId" element={<GoalPage />} />
        <Route path="orgs/:orgId/goals/:goalId/:tab" element={<GoalPage />} />
        <Route path="orgs/:orgId/issues" element={<IssuesPage />} />
        <Route path="orgs/:orgId/issues/:issueId" element={<IssuePage />} />
        <Route path="orgs/:orgId/approvals" element={<ApprovalsPage />} />
        <Route path="orgs/:orgId/approvals/:approvalId" element={<ApprovalPage />} />
        <Route path="orgs/:orgId/projects" element={<ProjectsPage />} />
        <Route path="orgs/:orgId/projects/:projectId" element={<ProjectPage />} />
        <Route path="orgs/:orgId/projects/:projectId/:tab" element={<ProjectPage />} />
        <Route path="orgs/:orgId/agents" element={<AgentsPage />} />
        <Route path="orgs/:orgId/agents/new" element={<NewAgentPage />} />
        <Route path="orgs/:orgId/agents/:agentId" element={<AgentPage />} />
        <Route path="orgs/:orgId/agents/:agentId/:tab" element={<AgentPage />} />
        <Route path="orgs/:orgId/chats" element={<ChatsPage />} />
        <Route path="orgs/:orgId/chats/:chatId" element={<ChatPage />} />
      </Route>
    </Routes>
  );
}
