import type { OrganizationHierarchyMember } from "../api/access";
import type { Agent } from "../api/types";

export function organizationMembersWithAgentFallback(
  members: OrganizationHierarchyMember[],
  agents: Pick<Agent, "id" | "name">[],
  orgId: string,
): OrganizationHierarchyMember[] {
  if (members.length > 0) return members;
  return agents.map((agent) => ({
    id: `agent:${agent.id}`,
    orgId,
    principalType: "agent",
    principalId: agent.id,
    displayName: agent.name,
    status: "active",
    role: "member",
    reportsTo: null,
  }));
}
