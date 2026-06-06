from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.approvals import list_org_approvals
from packages.database.queries.issues import list_org_issues
from packages.database.queries.messenger import (
    get_thread_user_state,
    upsert_thread_user_state,
)
from packages.database.schema import Approval as ApprovalRow
from packages.database.schema import Issue as IssueRow
from packages.database.schema import MessengerThreadUserState
from packages.shared.constants.messenger import (
    MESSENGER_SYSTEM_THREAD_KINDS,
    MessengerSystemThreadKind,
    MessengerThreadKind,
)
from packages.shared.types.approval import ApprovalDetail
from packages.shared.types.messenger import (
    MarkMessengerThreadReadResponse,
    MessengerApprovalThreadItem,
    MessengerChatThreadDetail,
    MessengerIssueThreadItem,
    MessengerThreadBundle,
    MessengerThreadSummary,
)

from ._time import ensure_aware
from .chats import ChatService


class MessengerService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._chats = ChatService(session)

    async def list_thread_summaries(
        self, org_id: str, user_id: str
    ) -> list[MessengerThreadSummary]:
        chats = await self._chat_summaries(org_id, user_id)
        issues = await self.get_issues_thread(org_id, user_id)
        approvals = await self.get_approvals_thread(org_id, user_id)
        summaries = list(chats)
        if issues["detail"]["items"]:
            summaries.append(issues["summary"])
        if approvals["detail"]["items"]:
            summaries.append(approvals["summary"])
        summaries.sort(
            key=lambda item: (
                _parse_iso(item["latestActivityAt"]) or datetime.fromtimestamp(0, UTC),
                item["title"],
            ),
            reverse=True,
        )
        return summaries

    async def get_chat_thread(
        self, org_id: str, conversation_id: str, user_id: str
    ) -> MessengerChatThreadDetail | None:
        conversation = await self._chats.get(conversation_id, user_id=user_id)
        if conversation is None or conversation["orgId"] != org_id:
            return None
        return {
            "conversation": conversation,
            "messages": await self._chats.list_messages(conversation_id),
        }

    async def mark_thread_read(
        self,
        org_id: str,
        user_id: str,
        thread_key: str,
        last_read_at: datetime | None = None,
    ) -> MarkMessengerThreadReadResponse | None:
        read_at = last_read_at or datetime.now(UTC)
        if thread_key.startswith("chat:"):
            conversation_id = thread_key.removeprefix("chat:")
            conversation = await self._chats.get(conversation_id, user_id=user_id)
            if conversation is None or conversation["orgId"] != org_id:
                return None
            updated = await self._chats.update_user_state(
                conversation_id, {"unread": False}, user_id=user_id
            )
            if updated is None:
                return None
            return {
                "threadKey": thread_key,
                "lastReadAt": updated["lastReadAt"] or datetime.now(UTC).isoformat(),
            }

        if not _valid_synthetic_thread_key(thread_key):
            return None
        row = await upsert_thread_user_state(
            self._session,
            org_id=org_id,
            user_id=user_id,
            thread_key=thread_key,
            last_read_at=read_at,
        )
        return {"threadKey": thread_key, "lastReadAt": row.last_read_at.isoformat()}

    async def get_issues_thread(
        self, org_id: str, user_id: str
    ) -> MessengerThreadBundle:
        rows = await self._issue_rows_for_user(org_id, user_id)
        state = await get_thread_user_state(
            self._session, org_id=org_id, user_id=user_id, thread_key="issues"
        )
        items = [_issue_item(row, user_id) for row in rows]
        summary = _summary_from_items(
            thread_key="issues",
            kind="issues",
            title="Issues",
            subtitle=(
                f"{len(items)} tracked issue{'s' if len(items) != 1 else ''}"
                if items
                else "No tracked issues yet"
            ),
            empty_preview="Create or follow issues to populate this feed",
            href="/messenger/issues",
            items=cast(list[dict[str, Any]], items),
            state=state,
        )
        return {
            "summary": summary,
            "detail": {
                **summary,
                "description": "Followed issues, issues I created, issues assigned to me, and issues ready for my review",
                "items": cast(list[dict[str, Any]], items),
            },
        }

    async def get_approvals_thread(
        self, org_id: str, user_id: str
    ) -> MessengerThreadBundle:
        rows = list(await list_org_approvals(self._session, org_id))
        state = await get_thread_user_state(
            self._session, org_id=org_id, user_id=user_id, thread_key="approvals"
        )
        items = [_approval_item(row, user_id) for row in rows]
        summary = _summary_from_items(
            thread_key="approvals",
            kind="approvals",
            title="Approvals",
            subtitle=(
                f"{len(items)} approval{'s' if len(items) != 1 else ''}"
                if items
                else "No approvals yet"
            ),
            empty_preview="No approvals in this organization",
            href="/messenger/approvals",
            items=cast(list[dict[str, Any]], items),
            state=state,
        )
        return {
            "summary": summary,
            "detail": {
                **summary,
                "description": "Approvals needing attention",
                "items": cast(list[dict[str, Any]], items),
            },
        }

    async def get_system_thread(
        self,
        org_id: str,
        user_id: str,
        thread_kind: MessengerSystemThreadKind,
    ) -> MessengerThreadBundle | None:
        if thread_kind not in MESSENGER_SYSTEM_THREAD_KINDS:
            return None
        state = await get_thread_user_state(
            self._session, org_id=org_id, user_id=user_id, thread_key=thread_kind
        )
        title = _system_title(thread_kind)
        summary = _summary_from_items(
            thread_key=thread_kind,
            kind=thread_kind,
            title=title,
            subtitle=f"No {title.lower()} yet",
            empty_preview=f"No {title.lower()} yet",
            href=f"/messenger/system/{thread_kind}",
            items=[],
            state=state,
        )
        return {
            "summary": summary,
            "detail": {**summary, "description": title, "items": []},
        }

    async def _chat_summaries(
        self, org_id: str, user_id: str
    ) -> list[MessengerThreadSummary]:
        conversations = await self._chats.list_for_org(
            org_id, status="active", user_id=user_id
        )
        summaries: list[MessengerThreadSummary] = []
        for conversation in conversations:
            messages = await self._chats.list_messages(conversation["id"])
            latest_visible = next(
                (message for message in reversed(messages) if message["body"].strip()),
                None,
            )
            preview = (
                _format_preview(latest_visible["body"])
                if latest_visible is not None
                else _format_preview(conversation.get("summary"))
            )
            latest_activity_at = (
                latest_visible["createdAt"]
                if latest_visible is not None
                else conversation["lastMessageAt"] or conversation["updatedAt"]
            )
            summaries.append(
                {
                    "threadKey": f"chat:{conversation['id']}",
                    "kind": "chat",
                    "title": conversation["title"],
                    "subtitle": preview,
                    "preview": preview,
                    "latestActivityAt": latest_activity_at,
                    "lastReadAt": conversation["lastReadAt"],
                    "unreadCount": conversation["unreadCount"],
                    "needsAttention": conversation["needsAttention"],
                    "isPinned": conversation["isPinned"],
                    "href": f"/messenger/chat/{conversation['id']}",
                }
            )
        return summaries

    async def _issue_rows_for_user(self, org_id: str, user_id: str) -> list[IssueRow]:
        result = await self._session.execute(
            select(IssueRow)
            .where(
                IssueRow.org_id == org_id,
                or_(
                    IssueRow.created_by_user_id == user_id,
                    IssueRow.assignee_user_id == user_id,
                    IssueRow.reviewer_user_id == user_id,
                ),
            )
            .order_by(IssueRow.updated_at, IssueRow.created_at, IssueRow.id)
        )
        rows = list(result.scalars().all())
        if rows:
            return rows
        # Fallback keeps the thread useful before issue follow/access tables exist.
        return list(await list_org_issues(self._session, org_id))


def _summary_from_items(
    *,
    thread_key: str,
    kind: MessengerThreadKind,
    title: str,
    subtitle: str,
    empty_preview: str,
    href: str,
    items: list[dict[str, Any]],
    state: MessengerThreadUserState | None,
) -> MessengerThreadSummary:
    latest_values = [
        parsed
        for item in items
        if (parsed := _parse_iso(str(item["latestActivityAt"]))) is not None
    ]
    latest = max(latest_values, default=None)
    latest_item = next(
        (
            item
            for item in sorted(
                items,
                key=lambda entry: (
                    _parse_iso(str(entry["latestActivityAt"]))
                    or datetime.fromtimestamp(0, UTC)
                ),
                reverse=True,
            )
        ),
        None,
    )
    last_read_at = state.last_read_at if state is not None else None
    unread_count = sum(
        1
        for item in items
        if last_read_at is None
        or ensure_aware(
            _parse_iso(str(item["latestActivityAt"])) or datetime.fromtimestamp(0, UTC)
        )
        > ensure_aware(last_read_at)
    )
    return {
        "threadKey": thread_key,
        "kind": kind,
        "title": title,
        "subtitle": subtitle,
        "preview": latest_item["preview"] if latest_item is not None else empty_preview,
        "latestActivityAt": latest.isoformat() if latest is not None else None,
        "lastReadAt": last_read_at.isoformat() if last_read_at is not None else None,
        "unreadCount": unread_count,
        "needsAttention": unread_count > 0,
        "isPinned": False,
        "href": href,
    }


def _issue_item(row: IssueRow, user_id: str) -> MessengerIssueThreadItem:
    label = f"{row.identifier} · {row.title}" if row.identifier else row.title
    flags = [
        value
        for value, enabled in (
            ("created by me", row.created_by_user_id == user_id),
            ("assigned to me", row.assignee_user_id == user_id),
            ("review requested", row.reviewer_user_id == user_id),
        )
        if enabled
    ]
    subtitle = " · ".join([row.status, row.priority, *flags])
    return {
        "id": row.id,
        "threadKey": "issues",
        "kind": "issues",
        "title": label,
        "subtitle": subtitle,
        "body": subtitle,
        "preview": label,
        "href": f"/issues/{row.identifier or row.id}",
        "latestActivityAt": row.updated_at.isoformat(),
        "actions": [
            {
                "label": "Open issue",
                "href": f"/issues/{row.identifier or row.id}",
                "method": "GET",
            }
        ],
        "metadata": {
            "issueId": row.id,
            "issueIdentifier": row.identifier,
            "status": row.status,
            "priority": row.priority,
            "createdByMe": row.created_by_user_id == user_id,
            "assignedToMe": row.assignee_user_id == user_id,
            "reviewerForMe": row.reviewer_user_id == user_id,
        },
        "issueId": row.id,
        "issueIdentifier": row.identifier,
        "sourceCommentId": None,
        "sourceCommentAuthorLabel": None,
        "sourceCommentBody": None,
    }


def _approval_item(row: ApprovalRow, user_id: str) -> MessengerApprovalThreadItem:
    detail = _approval_detail(row)
    title = _approval_title(row)
    preview = _approval_preview(row)
    return {
        "id": row.id,
        "threadKey": "approvals",
        "kind": "approvals",
        "title": title,
        "subtitle": row.status,
        "body": preview,
        "preview": preview,
        "href": f"/messenger/approvals/{row.id}",
        "latestActivityAt": row.updated_at.isoformat(),
        "actions": [
            {
                "label": "Approve",
                "href": f"/approvals/{row.id}/approve",
                "method": "POST",
            },
            {
                "label": "Reject",
                "href": f"/approvals/{row.id}/reject",
                "method": "POST",
            },
        ],
        "metadata": {
            "approvalId": row.id,
            "status": row.status,
            "requestedByMe": row.requested_by_user_id == user_id,
        },
        "approval": detail,
    }


def _approval_detail(row: ApprovalRow) -> ApprovalDetail:
    return {
        "id": row.id,
        "orgId": row.org_id,
        "type": cast(Any, row.type),
        "status": cast(Any, row.status),
        "requestedByAgentId": row.requested_by_agent_id,
        "requestedByUserId": row.requested_by_user_id,
        "createdAt": row.created_at.isoformat(),
        "payload": row.payload,
        "decisionNote": row.decision_note,
        "decidedByUserId": row.decided_by_user_id,
        "decidedAt": row.decided_at.isoformat() if row.decided_at else None,
        "updatedAt": row.updated_at.isoformat(),
    }


def _approval_title(row: ApprovalRow) -> str:
    if row.type == "chat_issue_creation":
        return "Review proposed issue"
    if row.type == "chat_operation":
        return "Review proposed operation"
    return "Approval request"


def _approval_preview(row: ApprovalRow) -> str:
    payload = row.payload or {}
    candidate = payload.get("proposedIssue")
    if isinstance(candidate, dict):
        title = str(candidate.get("title") or "").strip()
        description = str(candidate.get("description") or "").strip()
        return (
            _format_preview(" · ".join(part for part in (title, description) if part))
            or "Approval request"
        )
    candidate = payload.get("operationProposal")
    if isinstance(candidate, dict):
        return (
            _format_preview(
                str(candidate.get("summary") or "Agent proposed an operation")
            )
            or "Agent proposed an operation"
        )
    return _format_preview(str(row.type)) or "Approval request"


def _format_preview(value: str | None, max_length: int = 140) -> str | None:
    if value is None:
        return None
    lines = []
    for raw_line in value.replace("\r\n", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        while line.startswith("#"):
            line = line[1:].strip()
        if line.startswith("- "):
            line = line[2:].strip()
        lines.append(line)
    if not lines:
        return None
    if len(lines) >= 2 and value.lstrip().startswith("#"):
        preview = f"{lines[0]}: {' '.join(lines[1:])}"
    else:
        preview = " ".join(lines)
    return preview[: max_length - 1] + "…" if len(preview) > max_length else preview


def _parse_iso(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _valid_synthetic_thread_key(thread_key: str) -> bool:
    return thread_key in {"issues", "approvals", *MESSENGER_SYSTEM_THREAD_KINDS}


def _system_title(thread_kind: str) -> str:
    return {
        "failed-runs": "Failed runs",
        "budget-alerts": "Budget alerts",
        "join-requests": "Join requests",
    }[thread_kind]
