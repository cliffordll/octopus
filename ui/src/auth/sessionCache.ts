import type { QueryClient } from "@tanstack/react-query";
import type { AuthSession } from "../api/access";

export function replaceAuthenticatedSession(queryClient: QueryClient, session: AuthSession | null) {
  queryClient.clear();
  queryClient.setQueryData(["auth-session"], session);
}
