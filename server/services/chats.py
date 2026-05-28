from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.activity_log import insert_activity_log
from packages.database.queries.agents import get_agent_by_id
from packages.database.queries.agent_skills import list_enabled_skill_keys
from packages.database.queries.chats import (
    create_conversation,
    create_message,
    get_conversation,
    get_conversation_user_state,
    list_conversations,
    list_messages,
    touch_conversation,
    update_conversation,
    upsert_conversation_user_state,
)
from packages.database.queries.organizations import get_organization_by_id
from packages.database.schema import ChatConversation as ChatConversationRow
from packages.database.schema import ChatConversationUserState
from packages.database.schema import ChatMessage as ChatMessageRow
from packages.runtimes import RuntimeExecutionContext, get_runtime_adapter
from packages.shared.constants.chat import (
    ChatConversationStatus,
    ChatIssueCreationMode,
    ChatMessageKind,
    ChatMessageRole,
    ChatMessageStatus,
)
from packages.shared.types.chat import (
    AddChatMessagePayload,
    ChatConversation,
    ChatMessage,
    CreateChatConversationPayload,
    CreatedChatMessages,
    UpdateChatConversationPayload,
    UpdateChatConversationUserStatePayload,
)


class ChatAvailabilityError(ValueError):
    pass


class ChatService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_org(
        self,
        org_id: str,
        *,
        status: str = "active",
        q: str | None = None,
        user_id: str | None = None,
    ) -> list[ChatConversation]:
        return [
            await self._to_conversation(row, user_id=user_id)
            for row in await list_conversations(
                self._session, org_id, status=status, q=q
            )
        ]

    async def get(
        self, conversation_id: str, *, user_id: str | None = None
    ) -> ChatConversation | None:
        row = await get_conversation(self._session, conversation_id)
        return (
            await self._to_conversation(row, user_id=user_id)
            if row is not None
            else None
        )

    async def create(
        self,
        org_id: str,
        payload: CreateChatConversationPayload,
        *,
        actor_type: str,
        actor_id: str,
    ) -> ChatConversation:
        org = await get_organization_by_id(self._session, org_id)
        if org is None:
            raise ValueError("Organization not found")
        preferred_agent_id = payload.get("preferredAgentId")
        if preferred_agent_id is not None:
            agent = await get_agent_by_id(self._session, preferred_agent_id)
            if agent is None or agent.org_id != org_id:
                raise ValueError("Preferred agent must belong to the same organization")
        row = await create_conversation(
            self._session,
            {
                "org_id": org_id,
                "title": payload.get("title", "New chat"),
                "summary": payload.get("summary"),
                "preferred_agent_id": preferred_agent_id,
                "issue_creation_mode": payload.get(
                    "issueCreationMode", org.default_chat_issue_creation_mode
                ),
                "plan_mode": payload.get("planMode", False),
                "created_by_user_id": actor_id if actor_type == "board" else None,
            },
        )
        await insert_activity_log(
            self._session,
            org_id=org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="chat.created",
            entity_type="chat",
            entity_id=row.id,
            details={"title": row.title},
        )
        return await self._to_conversation(row, user_id=actor_id)

    async def update(
        self,
        conversation_id: str,
        payload: UpdateChatConversationPayload,
        *,
        actor_type: str,
        actor_id: str,
    ) -> ChatConversation | None:
        current = await get_conversation(self._session, conversation_id)
        if current is None:
            return None
        fields: dict[str, object] = {}
        if "title" in payload:
            fields["title"] = payload["title"]
        if "summary" in payload:
            fields["summary"] = payload["summary"]
        if "preferredAgentId" in payload:
            preferred_agent_id = payload["preferredAgentId"]
            if preferred_agent_id is not None:
                agent = await get_agent_by_id(self._session, preferred_agent_id)
                if agent is None or agent.org_id != current.org_id:
                    raise ValueError(
                        "Preferred agent must belong to the same organization"
                    )
            fields["preferred_agent_id"] = preferred_agent_id
        if "routedAgentId" in payload:
            routed_agent_id = payload["routedAgentId"]
            if routed_agent_id is not None:
                agent = await get_agent_by_id(self._session, routed_agent_id)
                if agent is None or agent.org_id != current.org_id:
                    raise ValueError(
                        "Routed agent must belong to the same organization"
                    )
            fields["routed_agent_id"] = routed_agent_id
        if "primaryIssueId" in payload:
            fields["primary_issue_id"] = payload["primaryIssueId"]
        if "issueCreationMode" in payload:
            fields["issue_creation_mode"] = payload["issueCreationMode"]
        if "planMode" in payload:
            fields["plan_mode"] = payload["planMode"]
        if "status" in payload:
            fields["status"] = payload["status"]
            if payload["status"] == "resolved" and "resolvedAt" not in payload:
                fields["resolved_at"] = datetime.now(UTC)
        if "resolvedAt" in payload:
            resolved_at = payload["resolvedAt"]
            fields["resolved_at"] = (
                datetime.fromisoformat(resolved_at) if resolved_at is not None else None
            )
        row = await update_conversation(self._session, conversation_id, fields)
        if row is None:
            return None
        await insert_activity_log(
            self._session,
            org_id=row.org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="chat.updated",
            entity_type="chat",
            entity_id=row.id,
            details={"fields": sorted(fields)},
        )
        return await self._to_conversation(row, user_id=actor_id)

    async def update_user_state(
        self,
        conversation_id: str,
        payload: UpdateChatConversationUserStatePayload,
        *,
        user_id: str,
    ) -> ChatConversation | None:
        row = await get_conversation(self._session, conversation_id)
        if row is None:
            return None
        state = await upsert_conversation_user_state(
            self._session,
            org_id=row.org_id,
            conversation_id=row.id,
            user_id=user_id,
            pinned=payload.get("pinned"),
            unread=payload.get("unread"),
        )
        return await self._to_conversation(row, user_state=state)

    async def list_messages(self, conversation_id: str) -> list[ChatMessage]:
        return [
            self._to_message(row)
            for row in await list_messages(self._session, conversation_id)
        ]

    async def add_message_and_reply(
        self, conversation_id: str, payload: AddChatMessagePayload
    ) -> CreatedChatMessages:
        conversation = await get_conversation(self._session, conversation_id)
        if conversation is None:
            raise ValueError("Chat conversation not found")
        if conversation.preferred_agent_id is None:
            raise ChatAvailabilityError("Choose a chat agent before sending messages.")
        agent = await get_agent_by_id(self._session, conversation.preferred_agent_id)
        if (
            agent is None
            or agent.org_id != conversation.org_id
            or agent.status == "terminated"
        ):
            raise ChatAvailabilityError(
                "The selected chat agent is unavailable. Choose another agent before sending messages."
            )
        turn_id = str(uuid.uuid4())
        user_message_at = datetime.now(UTC)
        user_message = await create_message(
            self._session,
            {
                "org_id": conversation.org_id,
                "conversation_id": conversation.id,
                "role": "user",
                "kind": "message",
                "status": "completed",
                "body": payload["body"],
                "chat_turn_id": turn_id,
                "created_at": user_message_at,
                "updated_at": user_message_at,
            },
        )
        await touch_conversation(
            self._session, conversation.id, user_message.created_at
        )
        try:
            adapter = get_runtime_adapter(agent.agent_runtime_type)
        except ValueError as exc:
            raise ChatAvailabilityError(str(exc)) from exc
        config = {**agent.agent_runtime_config, "promptTemplate": payload["body"]}
        runtime_context = config.get("_octopus")
        if not isinstance(runtime_context, dict):
            runtime_context = {}
        config["_octopus"] = {
            **runtime_context,
            "desiredSkills": await list_enabled_skill_keys(self._session, agent.id),
        }
        result = await adapter.execute(
            RuntimeExecutionContext(
                run_id=f"chat-{conversation.id}-{uuid.uuid4()}",
                agent_id=agent.id,
                org_id=agent.org_id,
                agent_name=agent.name,
                config=config,
                on_log=_ignore_log,
            )
        )
        if result.timed_out:
            raise RuntimeError("Chat request timed out")
        if result.error_message or (result.exit_code or 0) != 0:
            raise RuntimeError(result.error_message or "Chat adapter execution failed")
        summary = str((result.result_json or {}).get("summary") or "").strip()
        if not summary:
            raise RuntimeError("Chat adapter returned no assistant reply")
        assistant_message_at = max(
            datetime.now(UTC), user_message_at + timedelta(microseconds=1)
        )
        assistant_message = await create_message(
            self._session,
            {
                "org_id": conversation.org_id,
                "conversation_id": conversation.id,
                "role": "assistant",
                "kind": "message",
                "status": "completed",
                "body": summary,
                "replying_agent_id": agent.id,
                "chat_turn_id": turn_id,
                "created_at": assistant_message_at,
                "updated_at": assistant_message_at,
            },
        )
        await touch_conversation(
            self._session, conversation.id, assistant_message.created_at
        )
        return {
            "messages": [
                self._to_message(user_message),
                self._to_message(assistant_message),
            ]
        }

    async def _to_conversation(
        self,
        row: ChatConversationRow,
        *,
        user_id: str | None = None,
        user_state: ChatConversationUserState | None = None,
    ) -> ChatConversation:
        if user_state is None and user_id is not None:
            user_state = await get_conversation_user_state(
                self._session,
                org_id=row.org_id,
                conversation_id=row.id,
                user_id=user_id,
            )
        is_unread = _is_unread(row, user_state)
        return {
            "id": row.id,
            "orgId": row.org_id,
            "status": cast(ChatConversationStatus, row.status),
            "title": row.title,
            "summary": row.summary,
            "latestReplyPreview": None,
            "searchPreview": None,
            "preferredAgentId": row.preferred_agent_id,
            "routedAgentId": row.routed_agent_id,
            "primaryIssueId": row.primary_issue_id,
            "primaryIssue": None,
            "issueCreationMode": cast(ChatIssueCreationMode, row.issue_creation_mode),
            "planMode": row.plan_mode,
            "createdByUserId": row.created_by_user_id,
            "lastMessageAt": _iso(row.last_message_at),
            "lastReadAt": _iso(
                user_state.last_read_at if user_state is not None else None
            ),
            "isPinned": user_state is not None and user_state.pinned_at is not None,
            "isUnread": is_unread,
            "unreadCount": 1 if is_unread else 0,
            "needsAttention": is_unread,
            "resolvedAt": _iso(row.resolved_at),
            "contextLinks": [],
            "chatRuntime": {
                "sourceType": "none",
                "sourceLabel": "No runtime selected",
                "runtimeAgentId": row.preferred_agent_id,
                "agentRuntimeType": None,
                "model": None,
                "available": False,
                "error": None,
            },
            "createdAt": row.created_at.isoformat(),
            "updatedAt": row.updated_at.isoformat(),
        }

    def _to_message(self, row: ChatMessageRow) -> ChatMessage:
        return {
            "id": row.id,
            "orgId": row.org_id,
            "conversationId": row.conversation_id,
            "role": cast(ChatMessageRole, row.role),
            "kind": cast(ChatMessageKind, row.kind),
            "status": cast(ChatMessageStatus, row.status),
            "body": row.body,
            "structuredPayload": row.structured_payload,
            "approvalId": row.approval_id,
            "replyingAgentId": row.replying_agent_id,
            "chatTurnId": row.chat_turn_id,
            "turnVariant": row.turn_variant,
            "supersededAt": _iso(row.superseded_at),
            "createdAt": row.created_at.isoformat(),
            "updatedAt": row.updated_at.isoformat(),
        }


async def _ignore_log(_: str, __: str) -> None:
    return None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _is_unread(
    row: ChatConversationRow, user_state: ChatConversationUserState | None
) -> bool:
    if user_state is None or row.last_message_at is None:
        return False
    return row.last_message_at > user_state.last_read_at
