import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { organizationsApi } from "../api/organizations";
import { Badge } from "../components/Badge";
import { ErrorNotice } from "../components/ErrorNotice";

export function OrganizationsPage() {
  const [name, setName] = useState("");
  const [budgetMonthlyCents, setBudgetMonthlyCents] = useState("");
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
      setBudgetMonthlyCents("");
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
        ...(budgetMonthlyCents.trim() ? { budgetMonthlyCents: Number(budgetMonthlyCents) } : {}),
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
                <Link to={`/orgs/${organization.id}/issues`}>{organization.name}</Link>
                <Badge>{organization.status}</Badge>
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
            月度预算（cents）
            <input
              min="0"
              type="number"
              value={budgetMonthlyCents}
              onChange={(event) => setBudgetMonthlyCents(event.target.value)}
            />
          </label>
          <label>
            品牌色
            <input value={brandColor} onChange={(event) => setBrandColor(event.target.value)} />
          </label>
          <label className="checkbox-row">
            <input
              checked={requireBoardApprovalForNewAgents}
              onChange={(event) => setRequireBoardApprovalForNewAgents(event.target.checked)}
              type="checkbox"
            />
            新建智能体需要审批
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
