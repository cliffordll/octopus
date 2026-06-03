from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from ._base import Base, new_uuid


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        Index("documents_company_updated_idx", "org_id", "updated_at"),
        Index("documents_company_created_idx", "org_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(Text)
    format: Mapped[str] = mapped_column(Text, nullable=False, default="markdown")
    latest_body: Mapped[str] = mapped_column(Text, nullable=False)
    latest_revision_id: Mapped[str | None] = mapped_column(String(36))
    latest_revision_number: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )
    created_by_agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="SET NULL")
    )
    created_by_user_id: Mapped[str | None] = mapped_column(Text)
    updated_by_agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="SET NULL")
    )
    updated_by_user_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DocumentRevision(Base):
    __tablename__ = "document_revisions"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "revision_number",
            name="document_revisions_document_revision_uq",
        ),
        Index(
            "document_revisions_company_document_created_idx",
            "org_id",
            "document_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False
    )
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    change_summary: Mapped[str | None] = mapped_column(Text)
    created_by_agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="SET NULL")
    )
    created_by_user_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class IssueDocument(Base):
    __tablename__ = "issue_documents"
    __table_args__ = (
        UniqueConstraint(
            "org_id",
            "issue_id",
            "key",
            name="issue_documents_company_issue_key_uq",
        ),
        UniqueConstraint("document_id", name="issue_documents_document_uq"),
        Index(
            "issue_documents_company_issue_updated_idx",
            "org_id",
            "issue_id",
            "updated_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id"), nullable=False
    )
    issue_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("issues.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
