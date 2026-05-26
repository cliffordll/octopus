# Database Migrations

本目录为 Step 4 阶段的迁移入口占位。

当前不集成 alembic：

- Step 4 仅落地 schema 映射、client/session 入口和首批 query 函数
- 测试环境使用 in-memory SQLite + `Base.metadata.create_all` 直接建表，不依赖迁移
- 生产部署使用 PostgreSQL 的真实迁移工具链由 Step 5 或之后阶段在确定部署形态时统一引入

后续引入建议：

- 选型集中在 alembic（与 SQLAlchemy 同源、async 支持成熟）
- migrations versions 目录与 schema 文件同源维护，避免 schema 与迁移不一致
- 引入时需要先与 A 在 `docs/step-04/A-CONSTRAINTS.md` 或新版步骤约束中确认范围

在 alembic 正式引入前，本目录只保留 `__init__.py` 维持 Python 包结构。
