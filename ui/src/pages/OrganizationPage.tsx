import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
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
    <>
      <header className="page-header">
        <div>
          <p className="eyebrow">Organization</p>
          <h1>{organization.data?.name ?? "载入中..."}</h1>
        </div>
        <OrgNavigation orgId={orgId} />
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
    </>
  );
}

export function OrgNavigation({ orgId }: { orgId: string }) {
  return (
    <nav className="local-nav" aria-label="组织导航">
      <Link to={`/orgs/${orgId}/issues`}>Issues</Link>
      <Link to={`/orgs/${orgId}/approvals`}>Approvals</Link>
      <Link to={`/orgs/${orgId}/projects`}>Projects</Link>
      <Link to={`/orgs/${orgId}/agents`}>Agents</Link>
      <Link to={`/orgs/${orgId}/chats`}>Chats</Link>
      <Link to={`/orgs/${orgId}`}>设置</Link>
    </nav>
  );
}
