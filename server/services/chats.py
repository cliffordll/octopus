from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Awaitable, Callable, Sequence, cast
import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.activity_log import insert_activity_log
from packages.database.queries.agents import get_agent_by_id
from packages.database.queries.agent_skills import list_enabled_skill_keys
from packages.database.queries.approvals import create_approval
from packages.database.queries.chats import (
    create_chat_attachment,
    create_context_link,
    create_conversation,
    create_message,
    delete_project_context_links,
    get_conversation,
    get_conversation_user_state,
    get_latest_incoming_message_preview,
    get_message,
    list_attachments_for_messages,
    list_conversations,
    list_context_links,
    list_messages,
    supersede_turn_messages,
    touch_conversation,
    update_conversation,
    update_message,
    upsert_conversation_user_state,
)
from packages.database.queries.issues import get_issue_by_id
from packages.database.queries.organizations import get_organization_by_id
from packages.database.queries.projects import get_project_by_id
from packages.database.schema import Agent as AgentRow
from packages.database.schema import Asset as AssetRow
from packages.database.schema import ChatAttachment as ChatAttachmentRow
from packages.database.schema import ChatContextLink as ChatContextLinkRow
from packages.database.schema import ChatConversation as ChatConversationRow
from packages.database.schema import ChatConversationUserState
from packages.database.schema import ChatMessage as ChatMessageRow
from packages.database.schema import Issue as IssueRow
from packages.database.schema import Project as ProjectRow
from packages.runtimes import RuntimeExecutionContext, get_runtime_adapter
from packages.shared.constants.chat import (
    ChatConversationStatus,
    ChatIssueCreationMode,
    CHAT_ISSUE_CREATION_MODES,
    ChatMessageKind,
    CHAT_MESSAGE_KINDS,
    ChatMessageRole,
    ChatMessageStatus,
)
from packages.shared.types.chat import (
    AddChatMessagePayload,
    ChatAttachment,
    ChatContextLink,
    ChatConversation,
    ChatLinkedEntity,
    ChatMessage,
    ChatPrimaryIssueSummary,
    ChatRuntimeDescriptor,
    ChatStreamTranscriptEntry,
    ConvertChatToIssuePayload,
    CreateChatAttachmentPayload,
    CreateChatContextLinkPayload,
    CreateChatConversationPayload,
    CreatedChatMessages,
    ResolveChatOperationProposalPayload,
    SetChatProjectContextPayload,
    UpdateChatConversationPayload,
    UpdateChatConversationUserStatePayload,
)
from .issues import IssueService


class ChatAvailabilityError(ValueError):
    pass


_CHAT_TRANSCRIPT_KEY = "__chatTranscript"


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
        await self._assert_context_links_belong_to_org(
            org_id, payload.get("contextLinks", [])
        )
        row = await create_conversation(
            self._session,
            {
                "org_id": org_id,
                "title": payload.get("title", "New chat"),
                "summary": payload.get("summary"),
                "preferred_agent_id": preferred_agent_id,
                "issue_creation_mode": payload.get(
                    "issueCreationMode",
                    _chat_issue_creation_mode(org.default_chat_issue_creation_mode),
                ),
                "plan_mode": payload.get("planMode", False),
                "created_by_user_id": actor_id if actor_type == "board" else None,
            },
        )
        for link in payload.get("contextLinks", []):
            await create_context_link(
                self._session,
                {
                    "org_id": org_id,
                    "conversation_id": row.id,
                    "entity_type": link["entityType"],
                    "entity_id": link["entityId"],
                    "metadata_json": link.get("metadata"),
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
            details={
                "title": row.title,
                "contextLinkCount": len(payload.get("contextLinks", [])),
            },
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

    async def add_context_link(
        self,
        conversation_id: str,
        payload: CreateChatContextLinkPayload,
        *,
        actor_type: str,
        actor_id: str,
    ) -> ChatContextLink | None:
        row = await get_conversation(self._session, conversation_id)
        if row is None:
            return None
        await self._assert_context_links_belong_to_org(row.org_id, [payload])
        link = await create_context_link(
            self._session,
            {
                "org_id": row.org_id,
                "conversation_id": row.id,
                "entity_type": payload["entityType"],
                "entity_id": payload["entityId"],
                "metadata_json": payload.get("metadata"),
            },
        )
        await insert_activity_log(
            self._session,
            org_id=row.org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="chat.context_linked",
            entity_type="chat",
            entity_id=row.id,
            details=payload,
        )
        return (await self._hydrate_context_links([link]))[0]

    async def set_project_context(
        self,
        conversation_id: str,
        payload: SetChatProjectContextPayload,
        *,
        actor_type: str,
        actor_id: str,
    ) -> ChatConversation | None:
        row = await get_conversation(self._session, conversation_id)
        if row is None:
            return None
        project_id = payload.get("projectId")
        if project_id is not None:
            await self._assert_context_links_belong_to_org(
                row.org_id, [{"entityType": "project", "entityId": project_id}]
            )
        await delete_project_context_links(
            self._session, org_id=row.org_id, conversation_id=row.id
        )
        if project_id is not None:
            await create_context_link(
                self._session,
                {
                    "org_id": row.org_id,
                    "conversation_id": row.id,
                    "entity_type": "project",
                    "entity_id": project_id,
                    "metadata_json": None,
                },
            )
        await insert_activity_log(
            self._session,
            org_id=row.org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="chat.project_context_updated",
            entity_type="chat",
            entity_id=row.id,
            details={"projectId": project_id},
        )
        return await self._to_conversation(row, user_id=actor_id)

    async def list_messages(self, conversation_id: str) -> list[ChatMessage]:
        rows = await list_messages(self._session, conversation_id)
        attachments = await self._attachments_by_message_id(rows)
        return [self._to_message(row, attachments.get(row.id, [])) for row in rows]

    async def create_attachment(
        self,
        org_id: str,
        conversation_id: str,
        payload: CreateChatAttachmentPayload,
        *,
        actor_type: str,
        actor_id: str,
    ) -> ChatAttachment | None:
        conversation = await get_conversation(self._session, conversation_id)
        if conversation is None:
            return None
        if conversation.org_id != org_id:
            raise ValueError("Chat conversation does not belong to organization")
        message = await get_message(
            self._session,
            conversation_id=conversation.id,
            message_id=payload["messageId"],
        )
        if message is None:
            raise FileNotFoundError("Chat message not found")
        asset, attachment = await create_chat_attachment(
            self._session,
            asset_fields={
                "org_id": org_id,
                "provider": payload["provider"],
                "object_key": payload["objectKey"],
                "content_type": payload["contentType"],
                "byte_size": payload["byteSize"],
                "sha256": payload["sha256"],
                "original_filename": payload.get("originalFilename"),
                "created_by_agent_id": actor_id if actor_type == "agent" else None,
                "created_by_user_id": actor_id if actor_type != "agent" else None,
            },
            attachment_fields={
                "org_id": org_id,
                "conversation_id": conversation.id,
                "message_id": message.id,
            },
        )
        await insert_activity_log(
            self._session,
            org_id=org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="chat.attachment_added",
            entity_type="chat",
            entity_id=conversation.id,
            details={
                "attachmentId": attachment.id,
                "messageId": message.id,
                "originalFilename": asset.original_filename,
                "contentType": asset.content_type,
            },
        )
        return self._to_attachment(attachment, asset)

    async def convert_to_issue(
        self,
        conversation_id: str,
        payload: ConvertChatToIssuePayload,
        *,
        actor_type: str,
        actor_id: str,
    ) -> dict[str, Any] | None:
        conversation = await get_conversation(self._session, conversation_id)
        if conversation is None:
            return None
        proposal = await self._issue_proposal_for_conversion(conversation, payload)
        issue = await IssueService(self._session).create_issue(
            conversation.org_id,
            {
                "title": proposal["title"],
                "description": proposal.get("description"),
                "priority": proposal.get("priority", "medium"),
                "projectId": proposal.get("projectId"),
                "goalId": proposal.get("goalId"),
                "parentId": proposal.get("parentId"),
                "assigneeAgentId": proposal.get("assigneeAgentId"),
                "assigneeUserId": proposal.get("assigneeUserId"),
                "reviewerAgentId": proposal.get("reviewerAgentId"),
                "reviewerUserId": proposal.get("reviewerUserId"),
                "originKind": "manual",
                "originId": conversation.id,
            },
            actor_type=actor_type,
            actor_id=actor_id,
        )
        row = await update_conversation(
            self._session,
            conversation.id,
            {"primary_issue_id": issue["id"]},
        )
        if row is not None:
            await create_context_link(
                self._session,
                {
                    "org_id": conversation.org_id,
                    "conversation_id": conversation.id,
                    "entity_type": "issue",
                    "entity_id": issue["id"],
                    "metadata_json": {"sourceMessageId": payload.get("messageId")},
                },
            )
        system_message = await create_message(
            self._session,
            {
                "org_id": conversation.org_id,
                "conversation_id": conversation.id,
                "role": "system",
                "kind": "system_event",
                "status": "completed",
                "body": f"Created issue {issue['identifier'] or issue['id']} from this chat conversation.",
                "structured_payload": {
                    "eventType": "issue_created",
                    "issueId": issue["id"],
                    "issueIdentifier": issue["identifier"],
                },
            },
        )
        await touch_conversation(
            self._session, conversation.id, system_message.created_at
        )
        await insert_activity_log(
            self._session,
            org_id=conversation.org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="chat.issue_converted",
            entity_type="chat",
            entity_id=conversation.id,
            details={
                "issueId": issue["id"],
                "issueIdentifier": issue["identifier"],
                "messageId": payload.get("messageId"),
                "systemMessageId": system_message.id,
            },
        )
        return {"issue": issue, "systemMessage": self._to_message(system_message)}

    async def resolve_operation_proposal(
        self,
        conversation_id: str,
        message_id: str,
        payload: ResolveChatOperationProposalPayload,
        *,
        actor_type: str,
        actor_id: str,
    ) -> dict[str, Any] | None:
        conversation = await get_conversation(self._session, conversation_id)
        if conversation is None:
            return None
        message = await get_message(
            self._session, conversation_id=conversation.id, message_id=message_id
        )
        if message is None or message.kind != "operation_proposal":
            raise ValueError("Operation proposal not found")
        current_payload = dict(message.structured_payload or {})
        current_state = current_payload.get("operationProposalState")
        if isinstance(current_state, dict) and current_state.get("status") not in {
            None,
            "pending",
        }:
            raise ValueError("Only pending operation proposals can be resolved")
        status = _operation_decision_status(str(payload["action"]))
        current_payload["operationProposalState"] = {
            "status": status,
            "decisionNote": payload.get("decisionNote"),
            "decidedByUserId": actor_id if actor_type == "board" else None,
            "decidedAt": datetime.now(UTC).isoformat(),
        }
        updated = await update_message(
            self._session,
            conversation_id=conversation.id,
            message_id=message.id,
            fields={"structured_payload": current_payload},
        )
        if updated is None:
            raise ValueError("Operation proposal not found")
        proposal = _proposal_payload(current_payload, "operationProposal") or {}
        summary = str(proposal.get("summary") or "operation proposal")
        event_type = (
            "operation_revision_requested"
            if payload["action"] == "requestRevision"
            else f"operation_{status}"
        )
        system_message = await create_message(
            self._session,
            {
                "org_id": conversation.org_id,
                "conversation_id": conversation.id,
                "role": "system",
                "kind": "system_event",
                "status": "completed",
                "body": _operation_decision_body(str(payload["action"]), summary),
                "structured_payload": {
                    "eventType": event_type,
                    "source": "chat",
                    "sourceMessageId": message.id,
                    "targetType": proposal.get("targetType"),
                    "targetId": proposal.get("targetId"),
                    "decisionNote": payload.get("decisionNote"),
                },
            },
        )
        await touch_conversation(
            self._session, conversation.id, system_message.created_at
        )
        await insert_activity_log(
            self._session,
            org_id=conversation.org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="chat.operation_proposal_resolved",
            entity_type="chat",
            entity_id=conversation.id,
            details={
                "messageId": message.id,
                "systemMessageId": system_message.id,
                "action": payload["action"],
                "decisionNote": payload.get("decisionNote"),
            },
        )
        return {
            "message": self._to_message(updated),
            "systemMessage": self._to_message(system_message),
        }

    async def _issue_proposal_for_conversion(
        self,
        conversation: ChatConversationRow,
        payload: ConvertChatToIssuePayload,
    ) -> dict[str, Any]:
        direct = payload.get("proposal")
        if isinstance(direct, dict):
            return _issue_proposal_from_payload(direct)
        message_id = payload.get("messageId")
        message: ChatMessageRow | None = None
        if message_id is not None:
            message = await get_message(
                self._session, conversation_id=conversation.id, message_id=message_id
            )
        if message is None:
            messages = await list_messages(self._session, conversation.id)
            message = next(
                (row for row in reversed(messages) if row.kind == "issue_proposal"),
                None,
            )
        if message is None or message.kind != "issue_proposal":
            raise ValueError("No issue proposal found for this conversation")
        return _issue_proposal_from_payload(message.structured_payload)

    async def add_message_and_reply(
        self,
        conversation_id: str,
        payload: AddChatMessagePayload,
        *,
        cancel_event: Any | None = None,
        on_stream_event: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        commit_after_user_message: bool = False,
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
        user_message_at = datetime.now(UTC)
        edit_user_message_id = payload.get("editUserMessageId")
        turn_id = str(uuid.uuid4())
        turn_variant = 0
        if edit_user_message_id is not None:
            previous = await get_message(
                self._session,
                conversation_id=conversation.id,
                message_id=edit_user_message_id,
            )
            if (
                previous is None
                or previous.role != "user"
                or previous.chat_turn_id is None
            ):
                raise ValueError("Edited user message was not found")
            turn_id = previous.chat_turn_id
            turn_variant = previous.turn_variant + 1
            await supersede_turn_messages(
                self._session,
                conversation_id=conversation.id,
                chat_turn_id=turn_id,
                at=user_message_at,
            )
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
                "turn_variant": turn_variant,
                "created_at": user_message_at,
                "updated_at": user_message_at,
            },
        )
        await touch_conversation(
            self._session, conversation.id, user_message.created_at
        )
        if on_stream_event is not None:
            await on_stream_event(
                {"type": "ack", "userMessage": self._to_message(user_message)}
            )
        if commit_after_user_message:
            await self._session.commit()
        try:
            adapter = get_runtime_adapter(agent.agent_runtime_type)
        except ValueError as exc:
            raise ChatAvailabilityError(str(exc)) from exc
        # Mirror upstream `chat-assistant.helpers.ts:154-208 buildPrompt`: ship
        # the adapter a JSON envelope with conversation metadata, context links
        # and the most recent 12 non-superseded messages so multi-turn agents
        # can see prior history. The trailing user message is included via the
        # `addMessage` flush above, so it is part of the slice.
        prompt_payload = await self._build_assistant_prompt(conversation, user_message)
        config = {**agent.agent_runtime_config, "promptTemplate": prompt_payload}
        runtime_context = config.get("_octopus")
        if not isinstance(runtime_context, dict):
            runtime_context = {}
        config["_octopus"] = {
            **runtime_context,
            "desiredSkills": await list_enabled_skill_keys(self._session, agent.id),
        }
        transcript: list[ChatStreamTranscriptEntry] = []

        async def capture_stream_event(event: dict[str, Any]) -> None:
            if event.get("type") == "transcript_entry" and isinstance(
                event.get("entry"), dict
            ):
                transcript.append(cast(ChatStreamTranscriptEntry, event["entry"]))
            if on_stream_event is not None:
                await on_stream_event(event)

        result = await adapter.execute(
            RuntimeExecutionContext(
                run_id=f"chat-{conversation.id}-{uuid.uuid4()}",
                agent_id=agent.id,
                org_id=agent.org_id,
                agent_name=agent.name,
                config=config,
                on_log=_ignore_log,
                cancel_event=cancel_event,
                on_stream_event=(
                    capture_stream_event if on_stream_event is not None else None
                ),
            )
        )
        if result.timed_out:
            raise RuntimeError("Chat request timed out")
        if result.error_message or (result.exit_code or 0) != 0:
            raise RuntimeError(result.error_message or "Chat adapter execution failed")
        summary = str((result.result_json or {}).get("summary") or "").strip()
        if not summary:
            raise RuntimeError("Chat adapter returned no assistant reply")
        result_json = result.result_json or {}
        assistant_kind = _assistant_kind(result_json.get("kind"))
        structured_payload = _with_persisted_transcript(
            _assistant_structured_payload(result_json), transcript
        )
        approval_id = await self._create_proposal_approval(
            conversation,
            kind=assistant_kind,
            structured_payload=structured_payload,
            requested_by_user_id=conversation.created_by_user_id,
            replying_agent_id=agent.id,
        )
        assistant_message_at = max(
            datetime.now(UTC), user_message_at + timedelta(microseconds=1)
        )
        assistant_message = await create_message(
            self._session,
            {
                "org_id": conversation.org_id,
                "conversation_id": conversation.id,
                "role": "assistant",
                "kind": assistant_kind,
                "status": "completed",
                "body": summary,
                "structured_payload": structured_payload,
                "approval_id": approval_id,
                "replying_agent_id": agent.id,
                "chat_turn_id": turn_id,
                "turn_variant": turn_variant,
                "created_at": assistant_message_at,
                "updated_at": assistant_message_at,
            },
        )
        await touch_conversation(
            self._session, conversation.id, assistant_message.created_at
        )
        if commit_after_user_message:
            await self._session.commit()
        return {
            "messages": [
                self._to_message(user_message),
                self._to_message(assistant_message),
            ]
        }

    async def _create_proposal_approval(
        self,
        conversation: ChatConversationRow,
        *,
        kind: str,
        structured_payload: dict[str, Any] | None,
        requested_by_user_id: str | None,
        replying_agent_id: str | None,
    ) -> str | None:
        if kind == "issue_proposal":
            approval = await create_approval(
                self._session,
                {
                    "org_id": conversation.org_id,
                    "type": "chat_issue_creation",
                    "requested_by_user_id": requested_by_user_id,
                    "payload": {
                        "chatConversationId": conversation.id,
                        "proposedByAgentId": replying_agent_id,
                        "proposedIssue": _proposal_payload(
                            structured_payload, "issueProposal"
                        ),
                    },
                },
            )
            return approval.id
        if kind == "operation_proposal":
            approval = await create_approval(
                self._session,
                {
                    "org_id": conversation.org_id,
                    "type": "chat_operation",
                    "requested_by_user_id": requested_by_user_id,
                    "payload": {
                        "chatConversationId": conversation.id,
                        "operationProposal": _proposal_payload(
                            structured_payload, "operationProposal"
                        ),
                    },
                },
            )
            return approval.id
        return None

    async def _build_assistant_prompt(
        self,
        conversation: ChatConversationRow,
        latest_user_message: ChatMessageRow,
    ) -> str:
        """Build the JSON envelope passed to the runtime adapter as ``promptTemplate``.

        Mirrors upstream ``chat-assistant.helpers.ts:154-208`` ``buildPrompt``:
        ships ``conversation`` metadata, hydrated ``contextLinks`` and the most
        recent 12 non-superseded messages (oldest first). The trailing entry is
        the message the agent should respond to.
        """

        messages = await list_messages(self._session, conversation.id)
        recent = [row for row in messages if row.superseded_at is None][-12:]
        if not any(row.id == latest_user_message.id for row in recent):
            recent.append(latest_user_message)
            recent = recent[-12:]
        context_links = await self._context_links_for_conversation(conversation.id)
        return json.dumps(
            {
                "conversation": {
                    "id": conversation.id,
                    "title": conversation.title,
                    "status": conversation.status,
                    "summary": conversation.summary,
                    "planMode": conversation.plan_mode,
                    "issueCreationMode": conversation.issue_creation_mode,
                    "preferredAgentId": conversation.preferred_agent_id,
                    "routedAgentId": conversation.routed_agent_id,
                    "primaryIssueId": conversation.primary_issue_id,
                },
                "contextLinks": [_context_link_summary(link) for link in context_links],
                "recentMessages": [
                    {
                        "id": row.id,
                        "role": row.role,
                        "kind": row.kind,
                        "status": row.status,
                        "body": row.body,
                        "structuredPayload": row.structured_payload,
                    }
                    for row in recent
                ],
            },
            ensure_ascii=False,
            indent=2,
        )

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
        context_links = await self._context_links_for_conversation(row.id)
        primary_issue = await self._primary_issue_summary(row.primary_issue_id)
        latest_reply_preview = await get_latest_incoming_message_preview(
            self._session, row.id
        )
        if latest_reply_preview is not None and len(latest_reply_preview) > 140:
            latest_reply_preview = latest_reply_preview[:140]
        return {
            "id": row.id,
            "orgId": row.org_id,
            "status": cast(ChatConversationStatus, row.status),
            "title": row.title,
            "summary": row.summary,
            "latestReplyPreview": latest_reply_preview,
            "searchPreview": None,
            "preferredAgentId": row.preferred_agent_id,
            "routedAgentId": row.routed_agent_id,
            "primaryIssueId": row.primary_issue_id,
            "primaryIssue": primary_issue,
            "issueCreationMode": _chat_issue_creation_mode(row.issue_creation_mode),
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
            "contextLinks": context_links,
            "chatRuntime": await self._chat_runtime_descriptor(row),
            "createdAt": row.created_at.isoformat(),
            "updatedAt": row.updated_at.isoformat(),
        }

    async def _chat_runtime_descriptor(
        self, row: ChatConversationRow
    ) -> ChatRuntimeDescriptor:
        agent_id = row.routed_agent_id or row.preferred_agent_id
        if agent_id is None:
            return {
                "sourceType": "none",
                "sourceLabel": "No runtime selected",
                "runtimeAgentId": None,
                "agentRuntimeType": None,
                "model": None,
                "available": False,
                "error": None,
            }
        agent = await get_agent_by_id(self._session, agent_id)
        if agent is None or agent.org_id != row.org_id:
            return {
                "sourceType": "agent",
                "sourceLabel": "Missing chat agent",
                "runtimeAgentId": agent_id,
                "agentRuntimeType": None,
                "model": None,
                "available": False,
                "error": "Selected chat agent was not found.",
            }
        available = agent.status != "terminated"
        return {
            "sourceType": "agent",
            "sourceLabel": agent.name,
            "runtimeAgentId": agent.id,
            "agentRuntimeType": agent.agent_runtime_type,
            "model": _string(agent.agent_runtime_config.get("model")),
            "available": available,
            "error": None if available else "Selected chat agent is terminated.",
        }

    async def _context_links_for_conversation(
        self, conversation_id: str
    ) -> list[ChatContextLink]:
        links = await list_context_links(self._session, [conversation_id])
        return await self._hydrate_context_links(links)

    async def _hydrate_context_links(
        self, rows: Sequence[ChatContextLinkRow]
    ) -> list[ChatContextLink]:
        issue_ids = [row.entity_id for row in rows if row.entity_type == "issue"]
        project_ids = [row.entity_id for row in rows if row.entity_type == "project"]
        agent_ids = [row.entity_id for row in rows if row.entity_type == "agent"]
        issue_map = {
            issue_id: await get_issue_by_id(self._session, issue_id)
            for issue_id in issue_ids
        }
        project_map = {
            project_id: await get_project_by_id(self._session, project_id)
            for project_id in project_ids
        }
        agent_map = {
            agent_id: await get_agent_by_id(self._session, agent_id)
            for agent_id in agent_ids
        }
        return [
            {
                "id": row.id,
                "orgId": row.org_id,
                "conversationId": row.conversation_id,
                "entityType": cast(Any, row.entity_type),
                "entityId": row.entity_id,
                "metadata": row.metadata_json,
                "entity": _linked_entity(
                    row.entity_type,
                    row.entity_id,
                    issue_map.get(row.entity_id),
                    project_map.get(row.entity_id),
                    agent_map.get(row.entity_id),
                ),
                "createdAt": row.created_at.isoformat(),
                "updatedAt": row.updated_at.isoformat(),
            }
            for row in rows
        ]

    async def _primary_issue_summary(
        self, issue_id: str | None
    ) -> ChatPrimaryIssueSummary | None:
        if issue_id is None:
            return None
        issue = await get_issue_by_id(self._session, issue_id)
        if issue is None:
            return None
        return {
            "id": issue.id,
            "identifier": issue.identifier,
            "title": issue.title,
            "status": issue.status,
            "priority": issue.priority,
        }

    async def _assert_context_links_belong_to_org(
        self,
        org_id: str,
        links: Sequence[CreateChatContextLinkPayload | dict[str, str]],
    ) -> None:
        for link in links:
            entity_type = link["entityType"]
            entity_id = link["entityId"]
            if entity_type == "issue":
                issue = await get_issue_by_id(self._session, entity_id)
                if issue is None or issue.org_id != org_id:
                    raise ValueError(
                        "Issue context must belong to the same organization"
                    )
                continue
            if entity_type == "project":
                project = await get_project_by_id(self._session, entity_id)
                if project is None or project.org_id != org_id:
                    raise ValueError(
                        "Project context must belong to the same organization"
                    )
                continue
            agent = await get_agent_by_id(self._session, entity_id)
            if agent is None or agent.org_id != org_id:
                raise ValueError("Agent context must belong to the same organization")

    async def _attachments_by_message_id(
        self, rows: Sequence[ChatMessageRow]
    ) -> dict[str, list[ChatAttachment]]:
        pairs = await list_attachments_for_messages(
            self._session, [row.id for row in rows]
        )
        attachments: dict[str, list[ChatAttachment]] = {}
        for attachment, asset in pairs:
            attachments.setdefault(attachment.message_id, []).append(
                self._to_attachment(attachment, asset)
            )
        return attachments

    def _to_message(
        self,
        row: ChatMessageRow,
        attachments: list[ChatAttachment] | None = None,
    ) -> ChatMessage:
        return {
            "id": row.id,
            "orgId": row.org_id,
            "conversationId": row.conversation_id,
            "role": cast(ChatMessageRole, row.role),
            "kind": cast(ChatMessageKind, row.kind),
            "status": cast(ChatMessageStatus, row.status),
            "body": row.body,
            "structuredPayload": _strip_chat_metadata_from_payload(
                row.structured_payload
            ),
            "approvalId": row.approval_id,
            "attachments": attachments or [],
            "transcript": _chat_transcript_from_payload(row.structured_payload),
            "replyingAgentId": row.replying_agent_id,
            "chatTurnId": row.chat_turn_id,
            "turnVariant": row.turn_variant,
            "supersededAt": _iso(row.superseded_at),
            "createdAt": row.created_at.isoformat(),
            "updatedAt": row.updated_at.isoformat(),
        }

    def _to_attachment(self, row: ChatAttachmentRow, asset: AssetRow) -> ChatAttachment:
        return {
            "id": row.id,
            "orgId": row.org_id,
            "conversationId": row.conversation_id,
            "messageId": row.message_id,
            "assetId": row.asset_id,
            "provider": asset.provider,
            "objectKey": asset.object_key,
            "contentType": asset.content_type,
            "byteSize": asset.byte_size,
            "sha256": asset.sha256,
            "originalFilename": asset.original_filename,
            "createdByAgentId": asset.created_by_agent_id,
            "createdByUserId": asset.created_by_user_id,
            "createdAt": row.created_at.isoformat(),
            "updatedAt": row.updated_at.isoformat(),
            "contentPath": f"/api/assets/{row.asset_id}/content",
        }


async def _ignore_log(_: str, __: str) -> None:
    return None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _chat_issue_creation_mode(value: object) -> ChatIssueCreationMode:
    if value == "manual":
        return "manual_approval"
    if isinstance(value, str) and value in CHAT_ISSUE_CREATION_MODES:
        return cast(ChatIssueCreationMode, value)
    return "manual_approval"


def _assistant_kind(value: object) -> str:
    if isinstance(value, str) and value in CHAT_MESSAGE_KINDS:
        return value
    return "message"


def _assistant_structured_payload(
    result_json: dict[str, Any],
) -> dict[str, Any] | None:
    value = result_json.get("structuredPayload")
    if isinstance(value, dict):
        return value
    return None


def _chat_transcript_from_payload(
    payload: dict[str, Any] | None,
) -> list[ChatStreamTranscriptEntry]:
    transcript = (payload or {}).get(_CHAT_TRANSCRIPT_KEY)
    if not isinstance(transcript, list):
        return []
    return [
        cast(ChatStreamTranscriptEntry, entry)
        for entry in transcript
        if isinstance(entry, dict)
    ]


def _strip_chat_metadata_from_payload(
    payload: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if payload is None:
        return None
    if _CHAT_TRANSCRIPT_KEY not in payload:
        return payload
    clean_payload = {
        key: value for key, value in payload.items() if key != _CHAT_TRANSCRIPT_KEY
    }
    return clean_payload or None


def _with_persisted_transcript(
    payload: dict[str, Any] | None,
    transcript: list[ChatStreamTranscriptEntry],
) -> dict[str, Any] | None:
    clean_payload = _strip_chat_metadata_from_payload(payload)
    if not transcript:
        return clean_payload
    return {
        **(clean_payload or {}),
        _CHAT_TRANSCRIPT_KEY: transcript,
    }


def _proposal_payload(
    structured_payload: dict[str, Any] | None, key: str
) -> dict[str, Any] | None:
    if structured_payload is None:
        return None
    value = structured_payload.get(key)
    return value if isinstance(value, dict) else structured_payload


def _issue_proposal_from_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    proposal = _proposal_payload(payload, "issueProposal")
    if proposal is None:
        raise ValueError("Issue proposal payload was incomplete")
    title = proposal.get("title")
    description = proposal.get("description")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("Issue proposal payload was incomplete")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("Issue proposal payload was incomplete")
    return proposal


def _operation_decision_status(action: str) -> str:
    if action == "approve":
        return "approved"
    if action == "requestRevision":
        return "revision_requested"
    return "rejected"


def _operation_decision_body(action: str, summary: str) -> str:
    if action == "approve":
        return f"Applied lightweight change: {summary}."
    if action == "requestRevision":
        return f"Requested changes before applying lightweight change: {summary}."
    return f"Rejected lightweight change: {summary}."


def _is_unread(
    row: ChatConversationRow, user_state: ChatConversationUserState | None
) -> bool:
    if user_state is None or row.last_message_at is None:
        return False
    return row.last_message_at > user_state.last_read_at


def _context_link_summary(link: ChatContextLink) -> dict[str, Any]:
    """Flatten a hydrated context link for the assistant prompt envelope.

    Mirrors upstream ``chat-assistant.helpers.ts:158-166`` ``contextSummary``:
    surfaces the linked entity's label/identifier/status/description/priority so
    the runtime can reason about the referenced issue/project/agent.
    """

    entity = link.get("entity")
    entity_data = entity if isinstance(entity, dict) else {}
    return {
        "entityType": link["entityType"],
        "entityId": link["entityId"],
        "label": entity_data.get("label"),
        "identifier": entity_data.get("identifier"),
        "status": entity_data.get("status"),
        "description": entity_data.get("description"),
        "priority": entity_data.get("priority"),
    }


def _linked_entity(
    entity_type: str,
    entity_id: str,
    issue: IssueRow | None,
    project: ProjectRow | None,
    agent: AgentRow | None,
) -> ChatLinkedEntity | None:
    if entity_type == "issue" and issue is not None:
        return cast(
            ChatLinkedEntity,
            {
                "type": "issue",
                "id": issue.id,
                "label": issue.title,
                "subtitle": issue.status,
                "identifier": issue.identifier,
                "status": issue.status,
                "description": issue.description,
                "priority": issue.priority,
                "href": f"/issues/{issue.identifier or issue.id}",
            },
        )
    if entity_type == "project" and project is not None:
        return cast(
            ChatLinkedEntity,
            {
                "type": "project",
                "id": project.id,
                "label": project.name,
                "subtitle": project.description,
                "identifier": None,
                "status": project.status,
                "href": f"/projects/{project.id}",
            },
        )
    if entity_type == "agent" and agent is not None:
        return cast(
            ChatLinkedEntity,
            {
                "type": "agent",
                "id": agent.id,
                "label": agent.name,
                "subtitle": agent.title,
                "identifier": None,
                "status": agent.status,
                "href": f"/agents/{agent.id}",
            },
        )
    return None
