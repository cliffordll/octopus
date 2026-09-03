import type { QueryClient } from "@tanstack/react-query";
import type { AuthSession } from "../api/access";

export const AUTH_SESSION_STALE_TIME_MS = 5_000;

export function replaceAuthenticatedSession(queryClient: QueryClient, session: AuthSession | null) {
  queryClient.clear();
  queryClient.setQueryData(["auth-session"], session);
}
