from __future__ import annotations

from alembic import op


MYSQL_TEXT_INDEX_LENGTH = 191


def mysql_text_index_lengths(*column_names: str) -> dict[str, int]:
    bind = op.get_bind()
    if bind is None or bind.dialect.name != "mysql":
        return {}
    return {column_name: MYSQL_TEXT_INDEX_LENGTH for column_name in column_names}
