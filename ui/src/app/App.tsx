import { Route, Routes } from "react-router-dom";
import { AppShell } from "../components/AppShell";
import { ApprovalPage } from "../pages/ApprovalPage";
import { ApprovalsPage } from "../pages/ApprovalsPage";
import { HomePage } from "../pages/HomePage";
import { IssuePage } from "../pages/IssuePage";
import { IssuesPage } from "../pages/IssuesPage";
import { OrganizationPage } from "../pages/OrganizationPage";
import { OrganizationsPage } from "../pages/OrganizationsPage";

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<HomePage />} />
        <Route path="organizations" element={<OrganizationsPage />} />
        <Route path="orgs/:orgId" element={<OrganizationPage />} />
        <Route path="orgs/:orgId/issues" element={<IssuesPage />} />
        <Route path="orgs/:orgId/issues/:issueId" element={<IssuePage />} />
        <Route path="orgs/:orgId/approvals" element={<ApprovalsPage />} />
        <Route path="orgs/:orgId/approvals/:approvalId" element={<ApprovalPage />} />
      </Route>
    </Routes>
  );
}
