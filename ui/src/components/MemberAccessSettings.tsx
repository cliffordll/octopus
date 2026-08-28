import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  accessApi,
  type OrganizationInvite,
  type OrganizationMember,
  type PermissionKey,
} from "../api/access";
import { ErrorNotice } from "./ErrorNotice";

const PERMISSIONS: Array<{ key: PermissionKey; label: string }> = [
  { key: "agents:create", label: "创建智能体" },
  { key: "agents:manage", label: "管理智能体" },
  { key: "skills:manage", label: "管理技能" },
  { key: "users:invite", label: "邀请成员" },
  { key: "users:manage_permissions", label: "管理成员权限" },
  { key: "tasks:assign", label: "分配任务" },
  { key: "approvals:decide", label: "处理审批" },
  { key: "organizations:manage", label: "管理组织" },
  { key: "documents:manage", label: "管理文档" },
  { key: "runtime:manage", label: "管理运行时" },
  { key: "costs:manage", label: "管理预算" },
  { key: "projects:manage", label: "管理项目" },
  { key: "goals:manage", label: "管理目标" },
  { key: "workspaces:manage", label: "管理工作区" },
];

function permissionLabel(permission: PermissionKey): string {
  return PERMISSIONS.find((item) => item.key === permission)?.label ?? permission;
}

function MemberRow({ member, orgId }: { member: OrganizationMember; orgId: string }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [selected, setSelected] = useState<PermissionKey[]>(() => member.permissions.map((grant) => grant.permissionKey));
  const save = useMutation({
    mutationFn: () => accessApi.updatePermissions(orgId, member.id, selected),
    onSuccess: () => {
      setEditing(false);
      void queryClient.invalidateQueries({ queryKey: ["organization-members", orgId] });
    },
  });
  const statusChange = useMutation({
    mutationFn: () =>
      accessApi.updateMemberStatus(
        orgId,
        member.id,
        member.status === "suspended" ? "active" : "suspended",
      ),
    onSuccess: () =>
      void queryClient.invalidateQueries({ queryKey: ["organization-members", orgId] }),
  });
  const permissionLabels = member.permissions.map((grant) => permissionLabel(grant.permissionKey));

  function toggle(permission: PermissionKey) {
    setSelected((current) =>
      current.includes(permission) ? current.filter((item) => item !== permission) : [...current, permission],
    );
  }

  return (
    <article className="member-row">
      <div className="member-heading">
        <span className="access-avatar">{member.displayName.slice(0, 1).toUpperCase()}</span>
        <span>
          <strong>{member.displayName}</strong>
          <small>{member.principalType === "agent" ? "智能体" : "Human"} · {member.role}</small>
        </span>
        <span className={`status-pill ${member.status}`}>{member.status === "active" ? "有效" : member.status}</span>
        <div
          aria-label="已授权权限"
          className="member-permission-preview"
          title={permissionLabels.length ? permissionLabels.join("、") : "未单独授权"}
        >
          {permissionLabels.length ? (
            permissionLabels.map((label) => <span className="badge" key={label}>{label}</span>)
          ) : (
            <span className="muted">未单独授权</span>
          )}
        </div>
        <div className="member-actions">
          <button className="ghost" onClick={() => setEditing((value) => !value)} type="button">
            {editing ? "取消" : "编辑权限"}
          </button>
          {member.role !== "owner" && (
            <button
              className="ghost"
              disabled={statusChange.isPending}
              onClick={() => statusChange.mutate()}
              type="button"
            >
              {member.status === "suspended" ? "恢复成员" : "暂停成员"}
            </button>
          )}
        </div>
      </div>
      {editing ? (
        <div className="permission-editor">
          <div className="permission-grid">
            {PERMISSIONS.map((permission) => (
              <label key={permission.key}>
                <input
                  checked={selected.includes(permission.key)}
                  onChange={() => toggle(permission.key)}
                  type="checkbox"
                />
                {permission.label}
              </label>
            ))}
          </div>
          {save.error && <ErrorNotice error={save.error} />}
          <button disabled={save.isPending} onClick={() => save.mutate()} type="button">保存权限</button>
        </div>
      ) : null}
    </article>
  );
}

function inviteStatus(invite: OrganizationInvite): string {
  if (invite.revokedAt) return "已撤销";
  if (invite.acceptedAt) return "已接受";
  if (new Date(invite.expiresAt).getTime() <= Date.now()) return "已过期";
  return "等待接受";
}

export function MemberAccessSettings({ orgId }: { orgId?: string }) {
  const queryClient = useQueryClient();
  const [createdLink, setCreatedLink] = useState<string | null>(null);
  const members = useQuery({
    enabled: Boolean(orgId),
    queryKey: ["organization-members", orgId],
    queryFn: () => accessApi.members(orgId || ""),
  });
  const invites = useQuery({
    enabled: Boolean(orgId),
    queryKey: ["organization-invites", orgId],
    queryFn: () => accessApi.invites(orgId || ""),
  });
  const createInvite = useMutation({
    mutationFn: () => accessApi.createInvite(orgId || "", "human"),
    onSuccess: (invite) => {
      setCreatedLink(invite.inviteUrl ? new URL(invite.inviteUrl, window.location.origin).toString() : null);
      void queryClient.invalidateQueries({ queryKey: ["organization-invites", orgId] });
    },
  });
  const revokeInvite = useMutation({
    mutationFn: (inviteId: string) => accessApi.revokeInvite(orgId || "", inviteId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["organization-invites", orgId] }),
  });

  if (!orgId) {
    return <section className="settings-empty-section"><p className="muted">请先选择组织，再管理成员。</p></section>;
  }

  return (
    <section className="settings-empty-section access-settings" aria-label="组织成员">
      <div className="settings-section-heading-copy">
        <p className="eyebrow">Organization Members</p>
        <div className="runtime-provider-title-line">
          <h1>组织成员</h1>
          <p className="muted">管理成员、邀请和组织权限。Human 与智能体使用同一套授权规则。</p>
        </div>
      </div>
      {(members.error || invites.error) && <ErrorNotice error={members.error || invites.error} />}
      <div className="invite-creator access-card">
        <span><strong>邀请 Human</strong><small>智能体继续通过组织内创建流程加入。</small></span>
        <button disabled={createInvite.isPending} onClick={() => createInvite.mutate()} type="button">创建邀请</button>
        {createdLink && <input aria-label="新邀请链接" readOnly value={createdLink} />}
      </div>
      <div className="access-scroll-area">
        <section>
          <h4>成员</h4>
          <div className="member-list">
            {members.isLoading && <p className="muted">正在加载成员...</p>}
            {members.data?.map((member) => <MemberRow key={member.id} member={member} orgId={orgId} />)}
          </div>
        </section>
        <section>
          <h4>邀请</h4>
          <div className="invite-list">
            {invites.data?.map((invite) => (
              <article className="invite-row" key={invite.id}>
                <span><strong>{invite.allowedJoinTypes}</strong><small>{new Date(invite.expiresAt).toLocaleString()}</small></span>
                <span className="status-pill">{inviteStatus(invite)}</span>
                {!invite.revokedAt && !invite.acceptedAt && (
                  <button className="ghost" disabled={revokeInvite.isPending} onClick={() => revokeInvite.mutate(invite.id)} type="button">撤销</button>
                )}
              </article>
            ))}
          </div>
        </section>
      </div>
    </section>
  );
}
