from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import delete, desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.schema import Document, DocumentRevision, IssueDocument


async def list_issue_documents(
    session: AsyncSession, issue_id: str
) -> Sequence[tuple[IssueDocument, Document]]:
    result = await session.execute(
        select(IssueDocument, Document)
        .join(Document, IssueDocument.document_id == Document.id)
        .where(IssueDocument.issue_id == issue_id)
        .order_by(IssueDocument.key.asc(), desc(Document.updated_at))
    )
    return cast(Sequence[tuple[IssueDocument, Document]], result.all())


async def get_issue_document_by_key(
    session: AsyncSession, issue_id: str, key: str
) -> tuple[IssueDocument, Document] | None:
    result = await session.execute(
        select(IssueDocument, Document)
        .join(Document, IssueDocument.document_id == Document.id)
        .where(IssueDocument.issue_id == issue_id, IssueDocument.key == key)
    )
    return cast(tuple[IssueDocument, Document] | None, result.first())


async def list_issue_document_revisions(
    session: AsyncSession, issue_id: str, key: str
) -> Sequence[DocumentRevision]:
    current = await get_issue_document_by_key(session, issue_id, key)
    if current is None:
        return []
    _, document = current
    result = await session.execute(
        select(DocumentRevision)
        .where(DocumentRevision.document_id == document.id)
        .order_by(desc(DocumentRevision.revision_number))
    )
    return result.scalars().all()


async def create_issue_document(
    session: AsyncSession,
    *,
    org_id: str,
    issue_id: str,
    key: str,
    fields: Mapping[str, Any],
) -> tuple[IssueDocument, Document, DocumentRevision]:
    now = datetime.now(UTC)
    document = Document(
        org_id=org_id,
        title=fields.get("title"),
        format=fields["format"],
        latest_body=fields["body"],
        latest_revision_number=1,
        created_by_agent_id=fields.get("created_by_agent_id"),
        created_by_user_id=fields.get("created_by_user_id"),
        updated_by_agent_id=fields.get("created_by_agent_id"),
        updated_by_user_id=fields.get("created_by_user_id"),
        created_at=now,
        updated_at=now,
    )
    session.add(document)
    await session.flush()
    revision = DocumentRevision(
        org_id=org_id,
        document_id=document.id,
        revision_number=1,
        body=fields["body"],
        change_summary=fields.get("change_summary"),
        created_by_agent_id=fields.get("created_by_agent_id"),
        created_by_user_id=fields.get("created_by_user_id"),
        created_at=now,
    )
    session.add(revision)
    await session.flush()
    document.latest_revision_id = revision.id
    link = IssueDocument(
        org_id=org_id,
        issue_id=issue_id,
        document_id=document.id,
        key=key,
        created_at=now,
        updated_at=now,
    )
    session.add(link)
    await session.flush()
    return link, document, revision


async def update_issue_document(
    session: AsyncSession,
    *,
    link: IssueDocument,
    document: Document,
    fields: Mapping[str, Any],
) -> tuple[IssueDocument, Document, DocumentRevision]:
    now = datetime.now(UTC)
    revision_number = document.latest_revision_number + 1
    revision = DocumentRevision(
        org_id=document.org_id,
        document_id=document.id,
        revision_number=revision_number,
        body=fields["body"],
        change_summary=fields.get("change_summary"),
        created_by_agent_id=fields.get("updated_by_agent_id"),
        created_by_user_id=fields.get("updated_by_user_id"),
        created_at=now,
    )
    session.add(revision)
    await session.flush()
    await session.execute(
        update(Document)
        .where(Document.id == document.id)
        .values(
            title=fields.get("title"),
            format=fields["format"],
            latest_body=fields["body"],
            latest_revision_id=revision.id,
            latest_revision_number=revision_number,
            updated_by_agent_id=fields.get("updated_by_agent_id"),
            updated_by_user_id=fields.get("updated_by_user_id"),
            updated_at=now,
        )
    )
    await session.execute(
        update(IssueDocument).where(IssueDocument.id == link.id).values(updated_at=now)
    )
    await session.flush()
    refreshed = await get_issue_document_by_key(session, link.issue_id, link.key)
    if refreshed is None:
        raise RuntimeError("Issue document disappeared during update")
    next_link, next_document = refreshed
    return next_link, next_document, revision


async def delete_issue_document(
    session: AsyncSession, issue_id: str, key: str
) -> tuple[IssueDocument, Document] | None:
    current = await get_issue_document_by_key(session, issue_id, key)
    if current is None:
        return None
    link, document = current
    await session.execute(delete(Document).where(Document.id == document.id))
    await session.flush()
    return link, document
