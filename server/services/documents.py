from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.documents import (
    create_issue_document,
    delete_issue_document,
    get_issue_document_by_key,
    list_issue_document_revisions,
    list_issue_documents,
    update_issue_document,
)
from packages.database.schema import Document, DocumentRevision, IssueDocument
from packages.shared.types.issue import (
    DocumentRevision as DocumentRevisionData,
    IssueDocument as IssueDocumentData,
    IssueDocumentSummary,
)


class DocumentService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_issue_documents(self, issue_id: str) -> list[IssueDocumentSummary]:
        rows = await list_issue_documents(self._session, issue_id)
        return [self._to_summary(link, document) for link, document in rows]

    async def get_issue_document_by_key(
        self, issue_id: str, key: str
    ) -> IssueDocumentData | None:
        current = await get_issue_document_by_key(self._session, issue_id, key)
        if current is None:
            return None
        link, document = current
        return self._to_document(link, document)

    async def list_issue_document_revisions(
        self, issue_id: str, key: str
    ) -> list[DocumentRevisionData]:
        current = await get_issue_document_by_key(self._session, issue_id, key)
        if current is None:
            return []
        link, _ = current
        revisions = await list_issue_document_revisions(self._session, issue_id, key)
        return [self._to_revision(link, revision) for revision in revisions]

    async def upsert_issue_document(
        self,
        *,
        org_id: str,
        issue_id: str,
        key: str,
        payload: Mapping[str, Any],
        actor_type: str,
        actor_id: str,
    ) -> tuple[IssueDocumentData, bool, bool]:
        current = await get_issue_document_by_key(self._session, issue_id, key)
        actor_fields = _actor_fields(actor_type, actor_id)
        fields = {
            "title": payload.get("title"),
            "format": payload["format"],
            "body": payload["body"],
            "change_summary": payload.get("changeSummary"),
            **actor_fields,
        }
        if current is None:
            link, document, _ = await create_issue_document(
                self._session,
                org_id=org_id,
                issue_id=issue_id,
                key=key,
                fields=fields,
            )
            return self._to_document(link, document), True, False
        link, document = current
        if payload.get("baseRevisionId") not in (None, document.latest_revision_id):
            raise ValueError("Document base revision does not match latest revision")
        unchanged = (
            document.title == payload.get("title")
            and document.format == payload["format"]
            and document.latest_body == payload["body"]
        )
        if unchanged:
            return self._to_document(link, document), False, True
        link, document, _ = await update_issue_document(
            self._session,
            link=link,
            document=document,
            fields={
                **fields,
                "updated_by_agent_id": actor_fields.get("created_by_agent_id"),
                "updated_by_user_id": actor_fields.get("created_by_user_id"),
            },
        )
        return self._to_document(link, document), False, False

    async def delete_issue_document(
        self, issue_id: str, key: str
    ) -> IssueDocumentSummary | None:
        removed = await delete_issue_document(self._session, issue_id, key)
        if removed is None:
            return None
        link, document = removed
        return self._to_summary(link, document)

    def _to_summary(
        self, link: IssueDocument, document: Document
    ) -> IssueDocumentSummary:
        return {
            "id": document.id,
            "orgId": document.org_id,
            "issueId": link.issue_id,
            "key": link.key,
            "title": document.title,
            "format": document.format,
            "latestRevisionId": document.latest_revision_id,
            "latestRevisionNumber": document.latest_revision_number,
            "createdByAgentId": document.created_by_agent_id,
            "createdByUserId": document.created_by_user_id,
            "updatedByAgentId": document.updated_by_agent_id,
            "updatedByUserId": document.updated_by_user_id,
            "createdAt": document.created_at.isoformat(),
            "updatedAt": document.updated_at.isoformat(),
        }

    def _to_document(
        self, link: IssueDocument, document: Document
    ) -> IssueDocumentData:
        return {
            **self._to_summary(link, document),
            "body": document.latest_body,
        }

    def _to_revision(
        self, link: IssueDocument, revision: DocumentRevision
    ) -> DocumentRevisionData:
        return {
            "id": revision.id,
            "orgId": revision.org_id,
            "documentId": revision.document_id,
            "issueId": link.issue_id,
            "key": link.key,
            "revisionNumber": revision.revision_number,
            "body": revision.body,
            "changeSummary": revision.change_summary,
            "createdByAgentId": revision.created_by_agent_id,
            "createdByUserId": revision.created_by_user_id,
            "createdAt": revision.created_at.isoformat(),
        }


def _actor_fields(actor_type: str, actor_id: str) -> dict[str, str | None]:
    if actor_type == "agent":
        return {"created_by_agent_id": actor_id, "created_by_user_id": None}
    if actor_type == "user":
        return {"created_by_agent_id": None, "created_by_user_id": actor_id}
    return {"created_by_agent_id": None, "created_by_user_id": actor_id}
