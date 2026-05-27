import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent, type PropsWithChildren } from "react";
import { NavLink, useParams } from "react-router-dom";
import { organizationsApi } from "../api/organizations";
import { ErrorNotice } from "../components/ErrorNotice";

export function OrganizationPage() {
  const { orgId = "" } = useParams();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const queryClient = useQueryClient();
  const organization = useQuery({
    queryKey: ["organization", orgId],
    queryFn: () => organizationsApi.get(orgId),
  });
  useEffect(() => {
    if (organization.data) {
      setName(organization.data.name);
      setDescription(organization.data.description ?? "");
    }
  }, [organization.data]);
  const update = useMutation({
    mutationFn: () =>
      organizationsApi.update(orgId, {
        name: name.trim(),
        description: description.trim() || null,
      }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["organization", orgId] }),
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    update.mutate();
  }
  if (organization.error) return <ErrorNotice error={organization.error} />;
  return (
    <OrgWorkspace orgId={orgId}>
      <header className="page-header">
        <div>
          <p className="eyebrow">Organization</p>
          <h1>{organization.data?.name ?? "载入中..."}</h1>
        </div>
      </header>
      <form className="panel form narrow" onSubmit={submit}>
        <label>
          组织名称
          <input value={name} onChange={(event) => setName(event.target.value)} required />
        </label>
        <label>
          描述
          <textarea value={description} onChange={(event) => setDescription(event.target.value)} />
        </label>
        {update.error && <ErrorNotice error={update.error} />}
        <button type="submit">保存组织</button>
      </form>
    </OrgWorkspace>
  );
}

export function OrgNavigation({ orgId }: { orgId: string }) {
  return (
    <aside className="org-sidebar">
      <p className="org-sidebar-label">Organization</p>
      <h2>管理</h2>
      <nav className="local-nav" aria-label="组织导航">
        <NavLink to={`/orgs/${orgId}/projects`}>项目</NavLink>
        <NavLink to={`/orgs/${orgId}/approvals`}>审批</NavLink>
        <NavLink end to={`/orgs/${orgId}`}>设置</NavLink>
      </nav>
    </aside>
  );
}

export function OrgWorkspace({ orgId, children }: PropsWithChildren<{ orgId: string }>) {
  return (
    <div className="org-workspace">
      <OrgNavigation orgId={orgId} />
      <div className="org-content">{children}</div>
    </div>
  );
}
