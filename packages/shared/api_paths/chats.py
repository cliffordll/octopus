ORG_CHAT_LIST_PATH = "/api/orgs/{orgId}/chats"
ORG_CHAT_ATTACHMENTS_PATH = "/api/orgs/{orgId}/chats/{chatId}/attachments"
CHAT_DETAIL_PATH = "/api/chats/{id}"
CHAT_MESSAGES_PATH = "/api/chats/{id}/messages"
CHAT_MESSAGES_STREAM_PATH = "/api/chats/{id}/messages/stream"
CHAT_MESSAGES_STREAM_STOP_PATH = "/api/chats/{id}/messages/stream/stop"
CHAT_USER_STATE_PATH = "/api/chats/{id}/user-state"
CHAT_CONTEXT_LINKS_PATH = "/api/chats/{id}/context-links"
CHAT_PROJECT_CONTEXT_PATH = "/api/chats/{id}/project-context"
CHAT_CONVERT_TO_ISSUE_PATH = "/api/chats/{id}/convert-to-issue"
CHAT_OPERATION_PROPOSAL_RESOLVE_PATH = (
    "/api/chats/{id}/messages/{messageId}/operation-proposal/resolve"
)
