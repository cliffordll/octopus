import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { organizationsApi } from "../api/organizations";
import { Badge } from "../components/Badge";
import { ErrorNotice } from "../components/ErrorNotice";
import { formatMoneyCents, statusLabel } from "../utils/display";

function organizationBudgetCents(organization: unknown): number | undefined {
  if (!organization || typeof organization !== "object" || !("budgetMonthlyCents" in organization)) return undefined;
  const value = organization.budgetMonthlyCents;
  return typeof value === "number" ? value : undefined;
}

export function OrganizationsPage() {
  const [name, setName] = useState("");
  const [budgetMonthlyDollars, setBudgetMonthlyDollars] = useState("");
  const [brandColor, setBrandColor] = useState("");
  const [requireBoardApprovalForNewAgents, setRequireBoardApprovalForNewAgents] = useState(false);
  const [defaultChatIssueCreationMode, setDefaultChatIssueCreationMode] = useState("manual_approval");
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const organizations = useQuery({
    queryKey: ["organizations"],
    queryFn: organizationsApi.list,
  });
  const create = useMutation({
    mutationFn: organizationsApi.create,
    onSuccess: (organization) => {
      setName("");
      setBudgetMonthlyDollars("");
      setBrandColor("");
      setRequireBoardApprovalForNewAgents(false);
      setDefaultChatIssueCreationMode("manual_approval");
      void queryClient.invalidateQueries({ queryKey: ["organizations"] });
      navigate(`/orgs/${organization.id}/agents/new`);
    },
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    const value = name.trim();
    if (value) {
      create.mutate({
        name: value,
        ...(budgetMonthlyDollars.trim() ? { budgetMonthlyCents: Math.round(Number(budgetMonthlyDollars) * 100) } : {}),
        ...(brandColor.trim() ? { brandColor: brandColor.trim() } : {}),
        requireBoardApprovalForNewAgents,
        defaultChatIssueCreationMode,
      });
    }
  }
  return (
    <>
      <header className="page-header">
        <div>
          <p className="eyebrow">Workspace</p>
          <h1>组织</h1>
        </div>
      </header>
      <div className="grid-two">
        <section className="panel">
          <h2>现有组织</h2>
          {organizations.isLoading && <p className="muted">载入中...</p>}
          {organizations.error && <ErrorNotice error={organizations.error} />}
          <div className="list">
            {organizations.data?.map((organization) => (
              <article className="row" key={organization.id}>
                <div>
                  <Link to={`/orgs/${organization.id}/issues`}>{organization.name}</Link>
                  <p className="muted">
                    {organization.urlKey} · 预算 {formatMoneyCents(organizationBudgetCents(organization))}
                  </p>
                </div>
                <Badge>{statusLabel(organization.status)}</Badge>
              </article>
            ))}
          </div>
        </section>
        <form className="panel form" onSubmit={submit}>
          <h2>创建组织</h2>
          <label>
            组织名称
            <input value={name} onChange={(event) => setName(event.target.value)} required />
          </label>
          <label>
            月度预算（美元）
            <input
              min="0"
              step="0.01"
              type="number"
              value={budgetMonthlyDollars}
              onChange={(event) => setBudgetMonthlyDollars(event.target.value)}
            />
          </label>
          <label>
            品牌色
            <input value={brandColor} onChange={(event) => setBrandColor(event.target.value)} />
          </label>
          <label className="checkbox-row">
            <input
              aria-label="新建智能体需要审批"
              checked={requireBoardApprovalForNewAgents}
              onChange={(event) => setRequireBoardApprovalForNewAgents(event.target.checked)}
              type="checkbox"
            />
            <span>新建智能体需要审批</span>
          </label>
          <label>
            默认聊天任务创建模式
            <select
              value={defaultChatIssueCreationMode}
              onChange={(event) => setDefaultChatIssueCreationMode(event.target.value)}
            >
              <option value="manual_approval">手动确认</option>
              <option value="auto_create">自动创建</option>
            </select>
          </label>
          {create.error && <ErrorNotice error={create.error} />}
          <button disabled={create.isPending} type="submit">
            新建组织
          </button>
        </form>
      </div>
    </>
  );
}
