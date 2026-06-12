from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.activity_log import insert_activity_log
from packages.database.schema import (
    ActivityLog as ActivityLogRow,
    ChatContextLink,
    ChatConversation,
    HeartbeatRun as HeartbeatRunRow,
    Issue as IssueRow,
)
from packages.shared.types.activity import (
    ActivityEvent,
    ActivityQuery,
    CreateActivityPayload,
    IssueRunSummary,
    RunIssueSummary,
)
from packages.shared.validators.activity import parse_activity_datetime

_SENSITIVE_KEY_PARTS = (
    "token",
    "apikey",
    "api_key",
    "authorization",
    "cookie",
    "secret",
    "password",
)
_REDACTED = "[REDACTED]"
_ISSUE_UPDATE_METADATA_KEYS = {
    "identifier",
    "issueIdentifier",
    "_previous",
    "source",
    "reopened",
    "reopenedFrom",
    "normalizedFromStatus",
    "normalizedReason",
}


class ActivityService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_org(
        self, org_id: str, query: ActivityQuery
    ) -> list[ActivityEvent]:
        statement = select(ActivityLogRow).where(
            ActivityLogRow.org_id == org_id,
            ActivityLogRow.action != "issue.read_marked",
        )
        statement = self._apply_filters(statement, query)
        statement = statement.order_by(
            ActivityLogRow.created_at.desc(), ActivityLogRow.id.desc()
        )
        statement = statement.offset(query.get("offset", 0)).limit(
            query.get("limit", 100)
        )
        rows = (await self._session.execute(statement)).scalars().all()
        visible = await self._remove_hidden_issue_activity(rows)
        return [self._to_activity_event(row) for row in visible]

    async def create(
        self, org_id: str, payload: CreateActivityPayload
    ) -> ActivityEvent:
        row = await insert_activity_log(
            self._session,
            org_id=org_id,
            actor_type=payload.get("actorType", "system"),
            actor_id=payload["actorId"],
            action=payload["action"],
            entity_type=payload["entityType"],
            entity_id=payload["entityId"],
            agent_id=payload.get("agentId"),
            run_id=payload.get("runId"),
            details=_redact(payload.get("details")),
        )
        return self._to_activity_event(row)

    async def for_issue(self, issue_id: str) -> list[ActivityEvent] | None:
        issue = await self.resolve_issue(issue_id)
        if issue is None:
            return None
        direct_rows = (
            (
                await self._session.execute(
                    select(ActivityLogRow)
                    .where(
                        ActivityLogRow.org_id == issue.org_id,
                        ActivityLogRow.entity_type == "issue",
                        ActivityLogRow.entity_id == issue.id,
                        ActivityLogRow.action != "issue.read_marked",
                    )
                    .order_by(
                        ActivityLogRow.created_at.desc(), ActivityLogRow.id.desc()
                    )
                )
            )
            .scalars()
            .all()
        )
        direct_events = [
            self._to_activity_event(row)
            for row in direct_rows
            if _should_show_issue_activity(row)
        ]
        chat_events = await self._related_chat_events_for_issue(issue)
        merged = [*direct_events, *chat_events]
        return sorted(merged, key=lambda event: event["createdAt"], reverse=True)

    async def runs_for_issue(self, issue_id: str) -> list[IssueRunSummary] | None:
        issue = await self.resolve_issue(issue_id)
        if issue is None:
            return None
        activity_run_ids = await self._activity_run_ids_for_issue(issue)
        rows = (
            (
                await self._session.execute(
                    select(HeartbeatRunRow)
                    .where(HeartbeatRunRow.org_id == issue.org_id)
                    .order_by(
                        HeartbeatRunRow.created_at.desc(), HeartbeatRunRow.id.desc()
                    )
                )
            )
            .scalars()
            .all()
        )
        runs = [
            row
            for row in rows
            if _issue_id_from_context(row.context_snapshot) == issue.id
            or row.id in activity_run_ids
        ]
        return [self._to_issue_run_summary(row, issue) for row in runs]

    async def issues_for_run(self, run_id: str) -> list[RunIssueSummary] | None:
        run = await self._session.get(HeartbeatRunRow, run_id)
        if run is None:
            return None
        issue_ids: list[str] = []
        context_issue_id = _issue_id_from_context(run.context_snapshot)
        if context_issue_id is not None:
            issue_ids.append(context_issue_id)
        rows = (
            (
                await self._session.execute(
                    select(ActivityLogRow.entity_id)
                    .where(
                        ActivityLogRow.org_id == run.org_id,
                        ActivityLogRow.run_id == run.id,
                        ActivityLogRow.entity_type == "issue",
                    )
                    .order_by(
                        ActivityLogRow.created_at.desc(), ActivityLogRow.id.desc()
                    )
                )
            )
            .scalars()
            .all()
        )
        for issue_id in rows:
            if issue_id not in issue_ids:
                issue_ids.append(issue_id)
        if not issue_ids:
            return []
        issues = (
            (
                await self._session.execute(
                    select(IssueRow).where(
                        IssueRow.org_id == run.org_id,
                        IssueRow.id.in_(issue_ids),
                        IssueRow.hidden_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        by_id = {issue.id: issue for issue in issues}
        return [
            self._to_run_issue_summary(by_id[issue_id])
            for issue_id in issue_ids
            if issue_id in by_id
        ]

    async def resolve_issue(self, raw_id: str) -> IssueRow | None:
        issue = (
            await self._session.execute(select(IssueRow).where(IssueRow.id == raw_id))
        ).scalar_one_or_none()
        if issue is not None:
            return issue
        if _looks_like_issue_identifier(raw_id):
            return (
                await self._session.execute(
                    select(IssueRow).where(IssueRow.identifier == raw_id)
                )
            ).scalar_one_or_none()
        return None

    def _apply_filters(self, statement: Any, query: ActivityQuery) -> Any:
        agent_id = query.get("agentId")
        if agent_id:
            statement = statement.where(
                or_(
                    ActivityLogRow.agent_id == agent_id,
                    and_(
                        ActivityLogRow.actor_type == "agent",
                        ActivityLogRow.actor_id == agent_id,
                    ),
                )
            )
        user_id = query.get("userId")
        if user_id:
            statement = statement.where(
                ActivityLogRow.actor_type == "user",
                ActivityLogRow.actor_id == user_id,
            )
        for key, column in (
            ("actorType", ActivityLogRow.actor_type),
            ("actorId", ActivityLogRow.actor_id),
            ("action", ActivityLogRow.action),
            ("entityType", ActivityLogRow.entity_type),
            ("entityId", ActivityLogRow.entity_id),
            ("runId", ActivityLogRow.run_id),
        ):
            value = query.get(key)
            if value:
                statement = statement.where(column == value)
        start_time = _normalize_datetime(
            parse_activity_datetime(query.get("startTime"))
        )
        end_time = _normalize_datetime(parse_activity_datetime(query.get("endTime")))
        if start_time is not None:
            statement = statement.where(ActivityLogRow.created_at >= start_time)
        if end_time is not None:
            statement = statement.where(ActivityLogRow.created_at <= end_time)
        return statement

    async def _remove_hidden_issue_activity(
        self, rows: Sequence[ActivityLogRow]
    ) -> list[ActivityLogRow]:
        issue_ids = {
            row.entity_id
            for row in rows
            if row.entity_type == "issue" and row.entity_id
        }
        if not issue_ids:
            return list(rows)
        visible_ids = set(
            (
                await self._session.execute(
                    select(IssueRow.id).where(
                        IssueRow.id.in_(issue_ids),
                        IssueRow.hidden_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        return [
            row
            for row in rows
            if row.entity_type != "issue" or row.entity_id in visible_ids
        ]

    async def _related_chat_events_for_issue(
        self, issue: IssueRow
    ) -> list[ActivityEvent]:
        linked_conversation_ids = set(
            (
                await self._session.execute(
                    select(ChatContextLink.conversation_id).where(
                        ChatContextLink.org_id == issue.org_id,
                        ChatContextLink.entity_type == "issue",
                        ChatContextLink.entity_id == issue.id,
                    )
                )
            )
            .scalars()
            .all()
        )
        candidate_rows = (
            (
                await self._session.execute(
                    select(ActivityLogRow)
                    .where(
                        ActivityLogRow.org_id == issue.org_id,
                        ActivityLogRow.entity_type == "chat",
                        ActivityLogRow.action.in_(
                            [
                                "chat.issue_converted",
                                "chat.context_linked",
                                "chat.created",
                            ]
                        ),
                    )
                    .order_by(
                        ActivityLogRow.created_at.desc(), ActivityLogRow.id.desc()
                    )
                )
            )
            .scalars()
            .all()
        )
        if not candidate_rows:
            return []
        conversation_ids = {row.entity_id for row in candidate_rows}
        titles = {
            conversation.id: conversation.title
            for conversation in (
                (
                    await self._session.execute(
                        select(ChatConversation).where(
                            ChatConversation.id.in_(conversation_ids),
                            ChatConversation.org_id == issue.org_id,
                        )
                    )
                )
                .scalars()
                .all()
            )
        }
        events: list[ActivityEvent] = []
        for row in candidate_rows:
            details = row.details if isinstance(row.details, dict) else {}
            is_related = (
                (
                    row.action == "chat.issue_converted"
                    and details.get("issueId") == issue.id
                )
                or (
                    row.action == "chat.context_linked"
                    and details.get("entityType") == "issue"
                    and details.get("entityId") == issue.id
                )
                or (
                    row.action == "chat.created"
                    and row.entity_id in linked_conversation_ids
                    and int(details.get("contextLinkCount") or 0) > 0
                )
            )
            if not is_related:
                continue
            event = self._to_activity_event(row)
            if row.entity_id in titles:
                event["details"] = {
                    **(event["details"] or {}),
                    "conversationTitle": titles[row.entity_id],
                }
            events.append(event)
        return events

    async def _activity_run_ids_for_issue(self, issue: IssueRow) -> set[str]:
        rows = (
            (
                await self._session.execute(
                    select(ActivityLogRow.run_id).where(
                        ActivityLogRow.org_id == issue.org_id,
                        ActivityLogRow.entity_type == "issue",
                        ActivityLogRow.entity_id == issue.id,
                        ActivityLogRow.run_id.is_not(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        return {row for row in rows if row is not None}

    def _to_activity_event(self, row: ActivityLogRow) -> ActivityEvent:
        return {
            "id": row.id,
            "orgId": row.org_id,
            "actorType": row.actor_type,
            "actorId": row.actor_id,
            "action": row.action,
            "entityType": row.entity_type,
            "entityId": row.entity_id,
            "agentId": row.agent_id,
            "runId": row.run_id,
            "details": _redact(row.details),
            "createdAt": row.created_at.isoformat(),
        }

    def _to_issue_run_summary(
        self, row: HeartbeatRunRow, issue: IssueRow
    ) -> IssueRunSummary:
        return {
            "runId": row.id,
            "status": row.status,
            "agentId": row.agent_id,
            "invocationSource": row.invocation_source,
            "runPurpose": row.run_purpose,
            "triggerDetail": row.trigger_detail,
            "createdAt": row.created_at.isoformat(),
            "startedAt": row.started_at.isoformat() if row.started_at else None,
            "finishedAt": row.finished_at.isoformat() if row.finished_at else None,
            "error": row.error,
            "summary": _run_summary(row.result_json),
            "issueId": issue.id,
            "issueIdentifier": issue.identifier,
            "issueTitle": issue.title,
            "projectId": issue.project_id,
            "goalId": issue.goal_id,
        }

    def _to_run_issue_summary(self, row: IssueRow) -> RunIssueSummary:
        return {
            "issueId": row.id,
            "identifier": row.identifier,
            "title": row.title,
            "status": row.status,
            "priority": row.priority,
        }


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            normalized = key_text.replace("-", "_").lower()
            if any(part in normalized for part in _SENSITIVE_KEY_PARTS):
                result[key_text] = _REDACTED
            else:
                result[key_text] = _redact(item)
        return result
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def _normalize_datetime(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


def _issue_id_from_context(context_snapshot: dict[str, Any] | None) -> str | None:
    snapshot = context_snapshot if isinstance(context_snapshot, dict) else {}
    value = snapshot.get("issueId") or snapshot.get("primaryIssueId")
    return value if isinstance(value, str) and value else None


def _run_summary(result_json: dict[str, Any] | None) -> str | None:
    if not isinstance(result_json, dict):
        return None
    for key in ("summary", "result", "message"):
        value = result_json.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _looks_like_issue_identifier(value: str) -> bool:
    prefix, separator, number = value.rpartition("-")
    return bool(prefix and separator and number.isdigit())


def _should_show_issue_activity(row: ActivityLogRow) -> bool:
    if row.action == "issue.document_updated":
        return False
    if row.action != "issue.updated":
        return True
    details = row.details if isinstance(row.details, dict) else {}
    changed_keys = [key for key in details if key not in _ISSUE_UPDATE_METADATA_KEYS]
    return changed_keys != ["description"]
