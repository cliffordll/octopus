"""default agents to all bundled skills

Revision ID: 20260612_000022
Revises: 20260610_000021
Create Date: 2026-06-12 00:00:22
"""

from __future__ import annotations

from datetime import UTC, datetime
import uuid

from alembic import op
import sqlalchemy as sa


revision = "20260612_000022"
down_revision = "20260610_000021"
branch_labels = None
depends_on = None

_BUNDLED_SKILL_KEYS = (
    "skills/para-memory-files",
    "skills/control-plane",
    "skills/create-agent",
    "skills/create-plugin",
    "skills/skill-creator",
    "skills/skill-optimizer",
    "skills/conversation-to-skill",
)


def upgrade() -> None:
    connection = op.get_bind()
    agents = list(
        connection.execute(
            sa.text(
                """
                select id, org_id
                from agents
                where status != 'terminated'
                """
            )
        ).mappings()
    )
    existing = {
        (row["agent_id"], row["skill_key"])
        for row in connection.execute(
            sa.text("select agent_id, skill_key from agent_enabled_skills")
        ).mappings()
    }
    now = datetime.now(UTC).isoformat()

    for agent in agents:
        for skill_key in _BUNDLED_SKILL_KEYS:
            pair = (agent["id"], skill_key)
            if pair in existing:
                continue
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
                    "org_id": agent["org_id"],
                    "agent_id": agent["id"],
                    "skill_key": skill_key,
                    "created_at": now,
                },
            )
            existing.add(pair)


def downgrade() -> None:
    pass
