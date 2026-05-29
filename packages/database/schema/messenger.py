from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from ._base import Base, new_uuid


class MessengerThreadUserState(Base):
    __tablename__ = "messenger_thread_user_states"
    __table_args__ = (
        Index("messenger_thread_user_states_org_user_idx", "org_id", "user_id"),
        UniqueConstraint(
            "org_id",
            "thread_key",
            "user_id",
            name="messenger_thread_user_states_org_thread_user_idx",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    thread_key: Mapped[str] = mapped_column(Text, nullable=False)
    last_read_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
