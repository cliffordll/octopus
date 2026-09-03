import { useQuery } from "@tanstack/react-query";
import { costsApi } from "../api/costs";
import type { CostDimensionRow } from "../api/types";
import { ErrorNotice } from "./ErrorNotice";

function dollars(cents: number | null | undefined): string {
  return `$${((cents ?? 0) / 100).toFixed(2)}`;
}

function costDimensionLabel(value: string | null | undefined): string {
  if (!value || value === "unattributed") return "未归属";
  return value;
}

function CostRows({
  rows,
  title,
  valueKey,
}: {
  rows: CostDimensionRow[];
  title: string;
  valueKey: "agentId" | "biller" | "projectId" | "provider";
}) {
  return (
    <div className="cost-settings-list">
      <h4>{title}</h4>
      {rows.length === 0 ? (
        <p className="muted">暂无成本记录。</p>
      ) : (
        rows.slice(0, 6).map((row) => (
          <div className="cost-settings-row" key={`${title}:${row[valueKey] ?? "unattributed"}`}>
            <span>{costDimensionLabel(row[valueKey])}</span>
            <strong>{dollars(row.costCents)}</strong>
          </div>
        ))
      )}
    </div>
  );
}

export function OrganizationCostPanel({ orgId }: { orgId: string }) {
  const summary = useQuery({ queryKey: ["cost-summary", orgId], queryFn: () => costsApi.summary(orgId) });
  const byAgent = useQuery({ queryKey: ["cost-by-agent", orgId], queryFn: () => costsApi.byAgent(orgId) });
  const byProvider = useQuery({ queryKey: ["cost-by-provider", orgId], queryFn: () => costsApi.byProvider(orgId) });
  const byBiller = useQuery({ queryKey: ["cost-by-biller", orgId], queryFn: () => costsApi.byBiller(orgId) });
  const byProject = useQuery({ queryKey: ["cost-by-project", orgId], queryFn: () => costsApi.byProject(orgId) });
  const dimensionRows = [byAgent.data ?? [], byProvider.data ?? [], byBiller.data ?? [], byProject.data ?? []];
  const costDataLoading = [summary, byAgent, byProvider, byBiller, byProject].some((query) => query.isPending);
  const hasCostData = (summary.data?.eventCount ?? 0) > 0 || dimensionRows.some((rows) => rows.length > 0);
  return (
    <section className="settings-empty-section settings-cost-section" aria-label="成本">
      {summary.error && <ErrorNotice error={summary.error} />}
      <div className="cost-settings-summary">
        <div><span>总成本</span><strong>{dollars(summary.data?.totalCostCents)}</strong></div>
        <div><span>事件数</span><strong>{summary.data?.eventCount ?? 0}</strong></div>
        <div><span>输入 tokens</span><strong>{summary.data?.inputTokens ?? 0}</strong></div>
        <div><span>输出 tokens</span><strong>{summary.data?.outputTokens ?? 0}</strong></div>
      </div>
      {!costDataLoading && !hasCostData ? (
        <div className="cost-settings-empty" role="status">
          <span aria-hidden="true" className="cost-settings-empty-icon">$</span>
          <div>
            <h2>暂无成本数据</h2>
            <p>智能体运行并上报 token 与费用后，成本会自动出现在这里。</p>
          </div>
          <div className="cost-settings-empty-dimensions" aria-label="成本汇总维度">
            <span>智能体</span>
            <span>Provider</span>
            <span>计费方</span>
            <span>项目</span>
          </div>
        </div>
      ) : (
        <div className="cost-settings-grid">
          <CostRows rows={byAgent.data ?? []} title="按智能体" valueKey="agentId" />
          <CostRows rows={byProvider.data ?? []} title="按 Provider" valueKey="provider" />
          <CostRows rows={byBiller.data ?? []} title="按计费方" valueKey="biller" />
          <CostRows rows={byProject.data ?? []} title="按项目" valueKey="projectId" />
        </div>
      )}
    </section>
  );
}
