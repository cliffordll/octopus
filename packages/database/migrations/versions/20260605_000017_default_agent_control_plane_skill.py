"""default agents to the control-plane skill

Revision ID: 20260605_000017
Revises: 20260603_000016
Create Date: 2026-06-05 00:00:17
"""

from __future__ import annotations

from datetime import UTC, datetime
import uuid

from alembic import op
import sqlalchemy as sa


revision = "20260605_000017"
down_revision = "20260603_000016"
branch_labels = None
depends_on = None

_OCTOPUS_SKILL_KEY = "skills/control-plane"


def upgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            """
            select agents.id as agent_id, agents.org_id as org_id
            from agents
            where agents.status != 'terminated'
              and not exists (
                select 1
                from agent_enabled_skills
                where agent_enabled_skills.agent_id = agents.id
                  and agent_enabled_skills.skill_key = :skill_key
              )
            """
        ),
        {"skill_key": _OCTOPUS_SKILL_KEY},
    ).mappings()
    now = datetime.now(UTC).isoformat()
    for row in rows:
        connection.execute(
            sa.text(
                """
                insert into agent_enabled_skills
                    (id, org_id, agent_id, skill_key, created_at)
                values
                    (:id, :org_id, :agent_id, :skill_key, :created_at)
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "org_id": row["org_id"],
                "agent_id": row["agent_id"],
                "skill_key": _OCTOPUS_SKILL_KEY,
                "created_at": now,
            },
        )


def downgrade() -> None:
    pass
