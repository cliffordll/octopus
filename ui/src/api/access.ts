import { jsonRequest, request } from "./client";

export interface AuthUser {
  id: string;
  name?: string;
  email: string;
}

export interface AuthSession {
  user: AuthUser;
  session?: { source?: string | null };
}

export function isInteractiveHumanSession(session: AuthSession | null | undefined): session is AuthSession {
  return Boolean(session);
}

export interface OrganizationMember {
  id: string;
  orgId: string;
  principalType: "user" | "agent";
  principalId: string;
  displayName: string;
  status: "pending" | "active" | "suspended";
  role: string;
  permissions: Array<{ permissionKey: PermissionKey; constraints: Record<string, unknown> | null }>;
  createdAt: string;
  updatedAt: string;
}

export type PermissionKey =
  | "agents:create"
  | "agents:manage"
  | "skills:manage"
  | "users:invite"
  | "users:manage_permissions"
  | "tasks:assign"
  | "approvals:decide"
  | "organizations:manage"
  | "documents:manage"
  | "runtime:manage"
  | "costs:manage"
  | "projects:manage"
  | "goals:manage"
  | "workspaces:manage";

export interface OrganizationInvite {
  id: string;
  orgId: string | null;
  inviteType: string;
  allowedJoinTypes: "human" | "agent" | "both";
  defaultsPayload: Record<string, unknown> | null;
  expiresAt: string;
  invitedByUserId: string | null;
  revokedAt: string | null;
  acceptedAt: string | null;
  acceptedByUserId: string | null;
  createdAt: string;
  updatedAt: string;
  token?: string;
  inviteUrl?: string;
}

export const authApi = {
  session: (): Promise<AuthSession | null> => request<AuthSession | null>("/api/auth/get-session"),
  signIn: (email: string, password: string): Promise<AuthSession> =>
    jsonRequest<AuthSession>("/api/auth/sign-in/email", "POST", { email, password }),
  signUp: (name: string, email: string, password: string): Promise<AuthSession> =>
    jsonRequest<AuthSession>("/api/auth/sign-up/email", "POST", { name, email, password }),
  signOut: (): Promise<{ success: boolean }> =>
    jsonRequest<{ success: boolean }>("/api/auth/sign-out", "POST", {}),
};

export const accessApi = {
  inspectInvite: (token: string): Promise<OrganizationInvite> =>
    request<OrganizationInvite>(`/api/invites/${encodeURIComponent(token)}`),
  acceptInvite: (token: string): Promise<OrganizationInvite> =>
    jsonRequest<OrganizationInvite>(`/api/invites/${encodeURIComponent(token)}/accept`, "POST", {}),
  members: (orgId: string): Promise<OrganizationMember[]> =>
    request<OrganizationMember[]>(`/api/orgs/${encodeURIComponent(orgId)}/members`),
  updatePermissions: (
    orgId: string,
    memberId: string,
    permissions: PermissionKey[],
  ): Promise<OrganizationMember> =>
    jsonRequest<OrganizationMember>(
      `/api/orgs/${encodeURIComponent(orgId)}/members/${encodeURIComponent(memberId)}/permissions`,
      "PATCH",
      { grants: permissions.map((permissionKey) => ({ permissionKey, constraints: null })) },
    ),
  updateMemberStatus: (
    orgId: string,
    memberId: string,
    status: "active" | "suspended",
  ): Promise<OrganizationMember> =>
    jsonRequest<OrganizationMember>(
      `/api/orgs/${encodeURIComponent(orgId)}/members/${encodeURIComponent(memberId)}/status`,
      "PATCH",
      { status },
    ),
  invites: (orgId: string): Promise<OrganizationInvite[]> =>
    request<OrganizationInvite[]>(`/api/orgs/${encodeURIComponent(orgId)}/invites`),
  createInvite: (
    orgId: string,
    allowedJoinTypes: OrganizationInvite["allowedJoinTypes"],
  ): Promise<OrganizationInvite> =>
    jsonRequest<OrganizationInvite>(`/api/orgs/${encodeURIComponent(orgId)}/invites`, "POST", {
      allowedJoinTypes,
    }),
  revokeInvite: (orgId: string, inviteId: string): Promise<OrganizationInvite> =>
    jsonRequest<OrganizationInvite>(
      `/api/orgs/${encodeURIComponent(orgId)}/invites/${encodeURIComponent(inviteId)}/revoke`,
      "POST",
      {},
    ),
};
