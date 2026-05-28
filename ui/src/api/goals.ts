import { jsonRequest, request } from "./client";
import type { CreateGoalPayload, Goal, GoalDependencies, UpdateGoalPayload } from "./types";

function goalRoot(goalId: string): string {
  return `/api/goals/${encodeURIComponent(goalId)}`;
}

export const goalsApi = {
  list: (orgId: string): Promise<Goal[]> =>
    request<Goal[]>(`/api/orgs/${encodeURIComponent(orgId)}/goals`, { method: "GET" }),
  get: (goalId: string): Promise<Goal> =>
    request<Goal>(goalRoot(goalId), { method: "GET" }),
  dependencies: (goalId: string): Promise<GoalDependencies> =>
    request<GoalDependencies>(`${goalRoot(goalId)}/dependencies`, { method: "GET" }),
  create: (orgId: string, payload: CreateGoalPayload): Promise<Goal> =>
    jsonRequest<Goal>(`/api/orgs/${encodeURIComponent(orgId)}/goals`, "POST", payload),
  update: (goalId: string, payload: UpdateGoalPayload): Promise<Goal> =>
    jsonRequest<Goal>(goalRoot(goalId), "PATCH", payload),
  remove: (goalId: string): Promise<Goal> =>
    request<Goal>(goalRoot(goalId), { method: "DELETE" }),
};
