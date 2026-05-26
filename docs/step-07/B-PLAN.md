# Step 7 Organization Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `PATCH /api/orgs/{orgId}` with payload validation, board access guard, organization ownership guard, atomic activity log emission, and the 17 contract assertions specified in `docs/step-07/B-SPEC.md` §10.3.

**Architecture:** Bottom-up across four layers per `B-SPEC.md` §4. Queries first, then a request-scoped session transaction refactor that enables atomic update + activity_log writes, then a service that orchestrates them, then the route that wires dependencies + validator + service. Every task is a TDD cycle. Every task ends with the four-step verification green.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 async, aiosqlite (dev), pytest 8 + pytest-asyncio (asyncio_mode = auto), ruff + pyright, PowerShell (Windows shell).

---

## Pre-requisites

Before starting Task 1, the working tree must satisfy:

1. **Branch off `f717d87`** (the `Feat/contracts step 07 (#16)` merge — A's contract additions, no B implementation yet).

   Verify current HEAD:
   ```powershell
   git log -1 --format="%h %s"
   ```
   If it shows `3c236bf feat: add organization patch endpoint with activity logging (step 7)` (the previous B implementation), branch off the parent:
   ```powershell
   git branch feat/server-phase-7-rebuild f717d87
   git checkout feat/server-phase-7-rebuild
   ```
   If HEAD already shows `f717d87`, create the branch directly:
   ```powershell
   git checkout -b feat/server-phase-7-rebuild
   ```

2. **venv must be ready.** Verify:
   ```powershell
   .venv\Scripts\python.exe --version
   .venv\Scripts\ruff.exe --version
   .venv\Scripts\python.exe -m pyright --version
   ```
   All three must print versions, not errors.

3. **Baseline four-step verification.** Run all four and capture the test count.
   ```powershell
   .venv\Scripts\ruff.exe check . --fix
   .venv\Scripts\ruff.exe format .
   .venv\Scripts\python.exe -m pytest -q
   .venv\Scripts\python.exe -m pyright --pythonpath .venv\Scripts\python.exe
   ```
   Expected: pytest 74 passed, pyright 0 errors. If anything fails or the count differs, stop and report — the base is contaminated.

## Verification commands (run after EVERY task)

```powershell
.venv\Scripts\ruff.exe check . --fix
.venv\Scripts\ruff.exe format .
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m pyright --pythonpath .venv\Scripts\python.exe
```

All four must be green before committing. The `--pythonpath` flag on pyright is required so imports resolve against the venv site-packages instead of the global Python (without it, pyright reports ~80 spurious "Import could not be resolved" errors).

## File Structure (locked decomposition)

| Path | Action | Task | Responsibility |
|---|---|---|---|
| `packages/database/queries/organizations.py` | Modify | 1 | Add `update_organization(session, organization_id, fields)` |
| `tests/contract/test_step4_database.py` | Extend | 1, 2 | Query-level tests for the two new helpers |
| `packages/database/queries/activity_log.py` | Create | 2 | `insert_activity_log(session, *, ...)` |
| `server/dependencies/database.py` | Modify | 3 | Wrap `get_session` in `async with session.begin()` |
| `server/services/orgs.py` | Modify | 4 | Add `ORG_UPDATE_TO_COLUMN` + `OrgService.update` |
| `server/routes/orgs.py` | Modify | 5 | Add `PATCH` route + `_extract_actor_identity` |
| `tests/contract/test_step7_org_management.py` | Create | 5 | 17 contract integration tests |
| `docs/step-07/ORGANIZATION-MANAGEMENT.md` | Create | 6 | B execution record |

---

### Task 1: Add `update_organization` query

**Files:**
- Modify: `packages/database/queries/organizations.py`
- Test: `tests/contract/test_step4_database.py` (append three tests)

- [ ] **Step 1: Write the failing tests**

Open `tests/contract/test_step4_database.py`. Add to the imports at the top:

```python
from packages.database.queries.organizations import update_organization
```

Append at the bottom of the file:

```python
async def test_update_organization_returns_updated_row(session: AsyncSession) -> None:
    async with async_transaction(session):
        session.add(
            Organization(
                id="org-upd-1",
                url_key="o-upd-1",
                name="Old Name",
                issue_prefix="OUP",
                description="old desc",
            )
        )

    async with async_transaction(session):
        updated = await update_organization(
            session,
            "org-upd-1",
            {"name": "New Name", "description": None},
        )

    assert updated is not None
    assert updated.name == "New Name"
    assert updated.description is None
    assert updated.updated_at is not None


async def test_update_organization_missing_returns_none(session: AsyncSession) -> None:
    async with async_transaction(session):
        result = await update_organization(session, "no-such-org", {"name": "x"})
    assert result is None


async def test_update_organization_empty_fields_returns_current(
    session: AsyncSession,
) -> None:
    async with async_transaction(session):
        session.add(
            Organization(
                id="org-upd-2",
                url_key="o-upd-2",
                name="Keep",
                issue_prefix="OK1",
            )
        )

    result = await update_organization(session, "org-upd-2", {})
    assert result is not None
    assert result.name == "Keep"
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
.venv\Scripts\python.exe -m pytest tests/contract/test_step4_database.py -k "update_organization" -v
```

Expected: ImportError on collection (function `update_organization` does not exist in `packages.database.queries.organizations`).

- [ ] **Step 3: Implement the query**

Replace the entire contents of `packages/database/queries/organizations.py` with:

```python
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..schema import Organization


async def list_organizations(session: AsyncSession) -> Sequence[Organization]:
    result = await session.execute(
        select(Organization).order_by(Organization.created_at)
    )
    return result.scalars().all()


async def get_organization_by_id(
    session: AsyncSession, organization_id: str
) -> Organization | None:
    result = await session.execute(
        select(Organization).where(Organization.id == organization_id)
    )
    return result.scalar_one_or_none()


async def update_organization(
    session: AsyncSession,
    organization_id: str,
    fields: Mapping[str, Any],
) -> Organization | None:
    if not fields:
        return await get_organization_by_id(session, organization_id)

    values = dict(fields)
    values["updated_at"] = datetime.now(UTC)

    result = await session.execute(
        update(Organization)
        .where(Organization.id == organization_id)
        .values(**values)
        .returning(Organization)
    )
    return result.scalar_one_or_none()
```

Behavior contract:
- Empty `fields` degrades to a pure read so callers do not need to branch.
- `updated_at` is refreshed by the query layer because the schema has no `onupdate=` per Step 4 upstream alignment.
- `RETURNING` returns the post-update row in one round trip; caller does not re-read.

- [ ] **Step 4: Run all four verifications**

```powershell
.venv\Scripts\ruff.exe check . --fix
.venv\Scripts\ruff.exe format .
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m pyright --pythonpath .venv\Scripts\python.exe
```

Expected: pytest 77 passed (74 baseline + 3 new), ruff/format clean, pyright 0 errors.

- [ ] **Step 5: Commit**

```powershell
git add packages/database/queries/organizations.py tests/contract/test_step4_database.py
git commit -m "feat(database): add update_organization query with returning row"
```

---

### Task 2: Add `insert_activity_log` query

**Files:**
- Create: `packages/database/queries/activity_log.py`
- Test: `tests/contract/test_step4_database.py` (append one test)

- [ ] **Step 1: Write the failing test**

Open `tests/contract/test_step4_database.py`. Add to the imports at the top:

```python
from packages.database.queries.activity_log import insert_activity_log
from packages.database.schema import ActivityLog
```

(`ActivityLog` is already exported from `packages.database.schema` per Step 4; the second import line may already exist — if so, do not duplicate it.)

Append at the bottom of the file:

```python
async def test_insert_activity_log_persists_row(session: AsyncSession) -> None:
    async with async_transaction(session):
        session.add(
            Organization(id="org-act", url_key="o-act", name="A", issue_prefix="AAA")
        )

    async with async_transaction(session):
        row = await insert_activity_log(
            session,
            org_id="org-act",
            actor_type="board",
            actor_id="user-1",
            action="organization.updated",
            entity_type="organization",
            entity_id="org-act",
            details={"name": "renamed"},
        )

    assert row.id is not None
    assert row.org_id == "org-act"
    assert row.action == "organization.updated"
    assert row.entity_type == "organization"
    assert row.entity_id == "org-act"
    assert row.details == {"name": "renamed"}
    assert row.created_at is not None
```

- [ ] **Step 2: Run test to verify it fails**

```powershell
.venv\Scripts\python.exe -m pytest tests/contract/test_step4_database.py::test_insert_activity_log_persists_row -v
```

Expected: ImportError on collection (`packages.database.queries.activity_log` module does not exist).

- [ ] **Step 3: Create the helper file**

Create `packages/database/queries/activity_log.py`:

```python
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..schema import ActivityLog


async def insert_activity_log(
    session: AsyncSession,
    *,
    org_id: str,
    actor_type: str,
    actor_id: str,
    action: str,
    entity_type: str,
    entity_id: str,
    agent_id: str | None = None,
    run_id: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> ActivityLog:
    row = ActivityLog(
        org_id=org_id,
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        agent_id=agent_id,
        run_id=run_id,
        details=dict(details) if details is not None else None,
    )
    session.add(row)
    await session.flush()
    return row
```

Behavior contract:
- Keyword-only arguments mirror upstream `logActivity` shape — cannot mis-position the eight required fields.
- `details` is defensively copied so the caller's mapping cannot be mutated through the ORM row.
- `flush` populates `id` and `created_at` server defaults so the caller can reference them immediately.

- [ ] **Step 4: Run all four verifications**

```powershell
.venv\Scripts\ruff.exe check . --fix
.venv\Scripts\ruff.exe format .
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m pyright --pythonpath .venv\Scripts\python.exe
```

Expected: pytest 78 passed (77 from Task 1 + 1 new), ruff/format clean, pyright 0 errors.

- [ ] **Step 5: Commit**

```powershell
git add packages/database/queries/activity_log.py tests/contract/test_step4_database.py
git commit -m "feat(database): add insert_activity_log helper for audit records"
```

---

### Task 3: Refactor `get_session` to request-scoped transaction

This refactor enables Task 4's service.update to write UPDATE + activity_log atomically without opening a nested transaction. See `B-SPEC.md` §4 "Key design decision" for the full rationale.

**Files:**
- Modify: `server/dependencies/database.py`

- [ ] **Step 1: Capture baseline test count**

```powershell
.venv\Scripts\python.exe -m pytest -q
```

Expected: 78 passed. Record this number — Step 3 must produce the same number.

- [ ] **Step 2: Apply the refactor**

Replace the entire contents of `server/dependencies/database.py` with:

```python
from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        async with session.begin():
            yield session
```

- [ ] **Step 3: Run all four verifications and confirm no regression**

```powershell
.venv\Scripts\ruff.exe check . --fix
.venv\Scripts\ruff.exe format .
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m pyright --pythonpath .venv\Scripts\python.exe
```

Expected: pytest 78 passed (same as Step 1), ruff/format clean, pyright 0 errors.

If any test fails, the failing route or service is opening its own transaction. Production Step 1-6 code does not call `async_transaction(session)` inside services; only test fixtures do, and those create sessions via `session_factory()` directly (not via `get_session`), so they are unaffected. If a failure appears, investigate before proceeding — do not move to Task 4.

- [ ] **Step 4: Commit**

```powershell
git add server/dependencies/database.py
git commit -m "refactor(server): scope db session in request-level transaction"
```

---

### Task 4: Add `OrgService.update`

A dedicated service-level unit test would duplicate Task 5's integration fixtures (in-memory engine + middleware actor injection). Per `B-SPEC.md` §10 the test cluster lives in `tests/contract/test_step7_org_management.py` and exercises the service through the route. For this task we implement the method and rely on pyright + the existing 78-test baseline staying green. Behavioral coverage lands with Task 5.

**Files:**
- Modify: `server/services/orgs.py`

- [ ] **Step 1: Implement the service**

Replace the entire contents of `server/services/orgs.py` with:

```python
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.activity_log import insert_activity_log
from packages.database.queries.organizations import (
    get_organization_by_id,
    list_organizations,
    update_organization,
)
from packages.database.schema import Organization
from packages.shared.constants.organization import OrganizationStatus
from packages.shared.types.organization import OrganizationDetail, OrganizationSummary

ORG_UPDATE_TO_COLUMN: dict[str, str] = {
    "name": "name",
    "description": "description",
    "budgetMonthlyCents": "budget_monthly_cents",
    "defaultChatIssueCreationMode": "default_chat_issue_creation_mode",
    "brandColor": "brand_color",
    "requireBoardApprovalForNewAgents": "require_board_approval_for_new_agents",
}


class OrgService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self) -> list[OrganizationSummary]:
        rows = await list_organizations(self._session)
        return [
            OrganizationSummary(
                id=row.id,
                urlKey=row.url_key,
                name=row.name,
                status=cast(OrganizationStatus, row.status),
            )
            for row in rows
        ]

    async def get(self, org_id: str) -> OrganizationDetail | None:
        row = await get_organization_by_id(self._session, org_id)
        if row is None:
            return None
        return _to_detail(row)

    async def update(
        self,
        org_id: str,
        payload: Mapping[str, Any],
        *,
        actor_type: str,
        actor_id: str,
    ) -> OrganizationDetail | None:
        column_updates = {
            ORG_UPDATE_TO_COLUMN[key]: value
            for key, value in payload.items()
            if key in ORG_UPDATE_TO_COLUMN
        }

        if not column_updates:
            row = await get_organization_by_id(self._session, org_id)
            return _to_detail(row) if row is not None else None

        updated = await update_organization(self._session, org_id, column_updates)
        if updated is None:
            return None
        await insert_activity_log(
            self._session,
            org_id=org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="organization.updated",
            entity_type="organization",
            entity_id=org_id,
            details=dict(payload),
        )
        return _to_detail(updated)


def _to_detail(row: Organization) -> OrganizationDetail:
    return OrganizationDetail(
        id=row.id,
        urlKey=row.url_key,
        name=row.name,
        status=cast(OrganizationStatus, row.status),
        description=row.description,
        issuePrefix=row.issue_prefix,
        issueCounter=row.issue_counter,
        budgetMonthlyCents=row.budget_monthly_cents,
        spentMonthlyCents=row.spent_monthly_cents,
        brandColor=row.brand_color,
        createdAt=row.created_at.isoformat(),
        updatedAt=row.updated_at.isoformat(),
    )
```

Key behaviors:
- `ORG_UPDATE_TO_COLUMN` is the single source of truth for the six-field whitelist per `B-SPEC.md` §9. Unknown payload keys are silently dropped (validator already rejected bad shapes).
- Empty `column_updates` → no UPDATE, no activity row, return current detail. Matches `B-SPEC.md` §8 empty payload special case.
- Successful update → `insert_activity_log` runs in the same request-scoped transaction (Task 3) so the audit row commits atomically with the data change.
- Action name is fixed to `organization.updated` per A §7.3 first-batch freeze.
- `details` carries raw camelCase payload so audit consumers see exactly what was requested.

- [ ] **Step 2: Run all four verifications**

```powershell
.venv\Scripts\ruff.exe check . --fix
.venv\Scripts\ruff.exe format .
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m pyright --pythonpath .venv\Scripts\python.exe
```

Expected: pytest 78 passed (same as Task 3 — no route consumes `update` yet), ruff/format clean, pyright 0 errors.

- [ ] **Step 3: Commit**

```powershell
git add server/services/orgs.py
git commit -m "feat(server): add OrgService.update with camelcase-to-column map"
```

---

### Task 5: Add `PATCH` route + 17 contract tests

This is the integration task. The 17 tests cover all 13 A §12 required assertions plus the 5 supplementary scenarios from `B-SPEC.md` §10.3.

**Files:**
- Create: `tests/contract/test_step7_org_management.py`
- Modify: `server/routes/orgs.py`

- [ ] **Step 1: Create the failing test file**

Create `tests/contract/test_step7_org_management.py`:

```python
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool
from starlette.responses import Response

from packages.database.clients import async_transaction
from packages.database.schema import (
    ActivityLog,
    Base,
    Organization,
    OrganizationOwnership,
)
from server.app import app as fastapi_app

POD_ID = "test-pod"


@fastapi_app.middleware("http")
async def _inject_test_actor(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    actor_type = request.headers.get("x-test-actor-type")
    if actor_type:
        request.state.actor = {
            "type": actor_type,
            "id": request.headers.get("x-test-actor-id", "test-actor"),
        }
    return await call_next(request)


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
async def session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as s:
        yield s


@pytest.fixture
def app(session_factory: async_sessionmaker[AsyncSession]) -> FastAPI:
    fastapi_app.state.session_factory = session_factory
    fastapi_app.state.settings = SimpleNamespace(pod_id=POD_ID)
    return fastapi_app


async def _seed_org(
    session: AsyncSession,
    *,
    owned: bool = True,
    pod_id: str = POD_ID,
    expires_at: datetime | None = None,
) -> str:
    org_id = str(uuid.uuid4())
    if expires_at is None:
        expires_at = datetime.now(UTC) + timedelta(hours=1)
    async with async_transaction(session):
        session.add(
            Organization(
                id=org_id,
                url_key=f"u-{org_id[:8]}",
                name="Test Org",
                issue_prefix=org_id[:6],
            )
        )
        if owned:
            session.add(
                OrganizationOwnership(
                    organization_id=org_id,
                    pod_id=pod_id,
                    expires_at=expires_at,
                )
            )
    return org_id


async def _http(
    app: FastAPI,
    method: str,
    path: str,
    *,
    actor_type: str | None = None,
    json: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    headers: dict[str, str] = {}
    if actor_type:
        headers["x-test-actor-type"] = actor_type
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.request(method, path, headers=headers, json=json)
    try:
        body: Any = response.json()
    except ValueError:
        body = response.text
    return response.status_code, body


# --- list (Step 6, included as A §12 baseline) ---


async def test_org_list_board_success(app: FastAPI) -> None:
    code, body = await _http(app, "GET", "/api/orgs", actor_type="board")
    assert code == 200
    assert isinstance(body, list)


async def test_org_list_missing_actor_returns_503(app: FastAPI) -> None:
    code, body = await _http(app, "GET", "/api/orgs")
    assert code == 503
    assert "Actor context" in body["detail"]


async def test_org_list_non_board_returns_403(app: FastAPI) -> None:
    code, body = await _http(app, "GET", "/api/orgs", actor_type="agent")
    assert code == 403
    assert "Board access required" in body["detail"]


# --- detail (Step 6, included as A §12 baseline) ---


async def test_org_detail_owned_returns_200(
    app: FastAPI, session: AsyncSession
) -> None:
    org_id = await _seed_org(session)
    code, body = await _http(app, "GET", f"/api/orgs/{org_id}")
    assert code == 200
    assert body["id"] == org_id
    assert "urlKey" in body
    assert "issuePrefix" in body


async def test_org_detail_missing_returns_404(app: FastAPI) -> None:
    code, body = await _http(app, "GET", f"/api/orgs/{uuid.uuid4()}")
    assert code == 404
    assert body["detail"] == "Organization not found"


# --- update (new in Step 7) ---


async def test_org_update_owned_board_returns_200(
    app: FastAPI, session: AsyncSession
) -> None:
    org_id = await _seed_org(session)
    code, body = await _http(
        app,
        "PATCH",
        f"/api/orgs/{org_id}",
        actor_type="board",
        json={"name": "Renamed Co", "description": "new desc"},
    )
    assert code == 200
    assert body["name"] == "Renamed Co"
    assert body["description"] == "new desc"
    assert body["id"] == org_id


async def test_org_update_changes_config_fields(
    app: FastAPI, session: AsyncSession
) -> None:
    org_id = await _seed_org(session)
    code, body = await _http(
        app,
        "PATCH",
        f"/api/orgs/{org_id}",
        actor_type="board",
        json={"brandColor": "#ff0000", "budgetMonthlyCents": 50000},
    )
    assert code == 200
    assert body["brandColor"] == "#ff0000"
    assert body["budgetMonthlyCents"] == 50000


async def test_org_update_partial_does_not_touch_other_fields(
    app: FastAPI, session: AsyncSession
) -> None:
    org_id = await _seed_org(session)
    code1, before = await _http(app, "GET", f"/api/orgs/{org_id}", actor_type="board")
    assert code1 == 200
    code2, after = await _http(
        app,
        "PATCH",
        f"/api/orgs/{org_id}",
        actor_type="board",
        json={"name": "Just renamed"},
    )
    assert code2 == 200
    assert after["name"] == "Just renamed"
    assert after["description"] == before["description"]
    assert after["budgetMonthlyCents"] == before["budgetMonthlyCents"]
    assert after["brandColor"] == before["brandColor"]


async def test_org_update_foreign_returns_403(
    app: FastAPI, session: AsyncSession
) -> None:
    org_id = await _seed_org(session, pod_id="other-pod")
    code, body = await _http(
        app,
        "PATCH",
        f"/api/orgs/{org_id}",
        actor_type="board",
        json={"name": "X"},
    )
    assert code == 403
    assert "another pod" in body["detail"]


async def test_org_update_expired_returns_409(
    app: FastAPI, session: AsyncSession
) -> None:
    expires = datetime.now(UTC) - timedelta(hours=1)
    org_id = await _seed_org(session, expires_at=expires)
    code, body = await _http(
        app,
        "PATCH",
        f"/api/orgs/{org_id}",
        actor_type="board",
        json={"name": "X"},
    )
    assert code == 409
    assert "expired" in body["detail"]


async def test_org_update_non_board_returns_403(
    app: FastAPI, session: AsyncSession
) -> None:
    org_id = await _seed_org(session)
    code, body = await _http(
        app,
        "PATCH",
        f"/api/orgs/{org_id}",
        actor_type="agent",
        json={"name": "X"},
    )
    assert code == 403
    assert "Board access required" in body["detail"]


async def test_org_update_missing_actor_returns_503(
    app: FastAPI, session: AsyncSession
) -> None:
    org_id = await _seed_org(session)
    code, body = await _http(app, "PATCH", f"/api/orgs/{org_id}", json={"name": "X"})
    assert code == 503
    assert "Actor context" in body["detail"]


async def test_org_update_invalid_payload_returns_422(
    app: FastAPI, session: AsyncSession
) -> None:
    org_id = await _seed_org(session)
    code, body = await _http(
        app,
        "PATCH",
        f"/api/orgs/{org_id}",
        actor_type="board",
        json={"budgetMonthlyCents": -100},
    )
    assert code == 422
    assert "budgetMonthlyCents" in body["detail"]


async def test_org_update_missing_org_returns_404(app: FastAPI) -> None:
    code, body = await _http(
        app,
        "PATCH",
        f"/api/orgs/{uuid.uuid4()}",
        actor_type="board",
        json={"name": "X"},
    )
    assert code == 404
    assert body["detail"] == "Organization not found"


async def test_org_update_missing_ownership_returns_403(
    app: FastAPI, session: AsyncSession
) -> None:
    org_id = await _seed_org(session, owned=False)
    code, body = await _http(
        app,
        "PATCH",
        f"/api/orgs/{org_id}",
        actor_type="board",
        json={"name": "X"},
    )
    assert code == 403
    assert "no ownership record" in body["detail"]


async def test_org_update_writes_activity_record(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(session)
    code, _ = await _http(
        app,
        "PATCH",
        f"/api/orgs/{org_id}",
        actor_type="board",
        json={"name": "Activity Test"},
    )
    assert code == 200

    async with session_factory() as verify:
        result = await verify.execute(
            select(ActivityLog).where(ActivityLog.org_id == org_id)
        )
        rows = result.scalars().all()
    assert len(rows) == 1
    record = rows[0]
    assert record.action == "organization.updated"
    assert record.entity_type == "organization"
    assert record.entity_id == org_id
    assert record.details == {"name": "Activity Test"}
    assert record.actor_type == "board"


async def test_org_update_empty_payload_no_activity(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(session)
    code, _ = await _http(
        app, "PATCH", f"/api/orgs/{org_id}", actor_type="board", json={}
    )
    assert code == 200

    async with session_factory() as verify:
        result = await verify.execute(
            select(ActivityLog).where(ActivityLog.org_id == org_id)
        )
        rows = result.scalars().all()
    assert rows == []
```

- [ ] **Step 2: Run tests to verify the new PATCH-related ones fail**

```powershell
.venv\Scripts\python.exe -m pytest tests/contract/test_step7_org_management.py -v
```

Expected:
- Read-side tests (`test_org_list_*`, `test_org_detail_*`) pass — they exercise Step 6 surface only
- All `test_org_update_*` tests fail with 405 Method Not Allowed (no PATCH route registered yet)

- [ ] **Step 3: Implement the route**

Replace the entire contents of `server/routes/orgs.py` with:

```python
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status

from packages.shared.api_paths.organizations import ORG_DETAIL_PATH, ORG_LIST_PATH
from packages.shared.types.organization import OrganizationDetail, OrganizationSummary
from packages.shared.validators.organization import validate_update_organization

from ..dependencies.orgs import get_org_service, get_owned_org_detail
from ..services.orgs import OrgService

router = APIRouter(tags=["orgs"])


def require_board_access(request: Request) -> None:
    actor = getattr(request.state, "actor", None)
    if actor is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Actor context is not configured for board-scoped org listing",
        )

    actor_type = None
    actor_kind = None
    actor_role = None
    if isinstance(actor, Mapping):
        actor_type = actor.get("type")
        actor_kind = actor.get("kind")
        actor_role = actor.get("role")
    else:
        actor_type = getattr(actor, "type", None)
        actor_kind = getattr(actor, "kind", None)
        actor_role = getattr(actor, "role", None)

    if actor_type == "board" or actor_kind == "board" or actor_role == "board":
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Board access required",
    )


def _extract_actor_identity(request: Request) -> tuple[str, str]:
    actor = getattr(request.state, "actor", None)
    if actor is None:
        return "system", "board"

    if isinstance(actor, Mapping):
        actor_type = actor.get("type") or actor.get("kind") or "system"
        actor_id = (
            actor.get("userId") or actor.get("id") or actor.get("agentId") or "board"
        )
    else:
        actor_type = (
            getattr(actor, "type", None) or getattr(actor, "kind", None) or "system"
        )
        actor_id = (
            getattr(actor, "userId", None)
            or getattr(actor, "id", None)
            or getattr(actor, "agentId", None)
            or "board"
        )

    return str(actor_type), str(actor_id)


@router.get(ORG_LIST_PATH)
async def list_orgs(
    _: None = Depends(require_board_access),
    service: OrgService = Depends(get_org_service),
) -> list[OrganizationSummary]:
    return await service.list()


@router.get(ORG_DETAIL_PATH)
async def get_org(
    org: OrganizationDetail = Depends(get_owned_org_detail),
) -> OrganizationDetail:
    return org


@router.patch(ORG_DETAIL_PATH)
async def update_org(
    request: Request,
    orgId: str,
    body: dict[str, Any] = Body(...),
    _: None = Depends(require_board_access),
    org: OrganizationDetail = Depends(get_owned_org_detail),
    service: OrgService = Depends(get_org_service),
) -> OrganizationDetail:
    try:
        payload = validate_update_organization(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    actor_type, actor_id = _extract_actor_identity(request)
    updated = await service.update(
        orgId,
        payload,
        actor_type=actor_type,
        actor_id=actor_id,
    )
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )
    return updated
```

Dependency ordering reproduces `B-SPEC.md` §7 error precedence:

| Order | Layer | Failure mode | Status |
|---|---|---|---|
| 1 | `require_board_access` (no DB) | actor missing | 503 |
| 2 | `require_board_access` | actor not board | 403 (`Board access required`) |
| 3 | `get_owned_org_detail` SELECT | org row not found | 404 |
| 4 | `get_owned_org_detail` → `assert_organization_owned` | ownership row missing | 403 (`no ownership record`) |
| 5 | `assert_organization_owned` | ownership owned by other pod | 403 (`another pod`) |
| 6 | `assert_organization_owned` | lease expired | 409 |
| 7 | route body | validator rejects payload | 422 |

- [ ] **Step 4: Run all four verifications**

```powershell
.venv\Scripts\ruff.exe check . --fix
.venv\Scripts\ruff.exe format .
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m pyright --pythonpath .venv\Scripts\python.exe
```

Expected: pytest 95 passed (78 from Task 4 + 17 new), ruff/format clean, pyright 0 errors.

Note: pytest may emit one deprecation warning on `HTTP_422_UNPROCESSABLE_ENTITY` (FastAPI prefers the renamed `HTTP_422_UNPROCESSABLE_CONTENT` in newer releases). The warning is informational; the assertion `code == 422` still holds. Do not change the constant — it is the same status code with the same numeric value, and changing it would diverge from Step 6's existing usage.

- [ ] **Step 5: Manual HTTP smoke**

Start the dev server in one terminal:

```powershell
.venv\Scripts\python.exe -m uvicorn server.app:app --port 8000
```

In a second terminal, exercise the production surface:

```powershell
curl -i http://127.0.0.1:8000/api/orgs
curl -i -X PATCH http://127.0.0.1:8000/api/orgs/some-id -H "Content-Type: application/json" -d "{}"
curl -i -X PATCH http://127.0.0.1:8000/api/orgs/some-id -H "Content-Type: application/json" -d "{\"name\":\"x\"}"
```

Expected: all three return 503 with `detail` mentioning "Actor context". This is correct — the production app has no actor injection middleware. This will be captured as a known gap in Task 6's documentation.

Stop the server with Ctrl+C.

- [ ] **Step 6: Commit**

```powershell
git add server/routes/orgs.py tests/contract/test_step7_org_management.py
git commit -m "feat(server): organization patch endpoint with activity logging (step 7)"
```

---

### Task 6: Write execution record

**Files:**
- Create: `docs/step-07/ORGANIZATION-MANAGEMENT.md`

- [ ] **Step 1: Write the execution record**

Create `docs/step-07/ORGANIZATION-MANAGEMENT.md` with the following sections, each populated with the exact content from the implementation just completed:

```markdown
# Step 7 Organization Management Execution Record

## 1. Scope and Authoritative Input

Scope covered: PATCH /api/orgs/{orgId} with payload validation, board access guard, organization ownership guard, atomic activity log emission. List and detail endpoints reused unchanged from Step 6.

Authoritative inputs consulted:
- `docs/step-07/A-CONSTRAINTS.md` §3 (range), §6.2 (frozen field set), §7 (access + write semantics + error codes), §12 (test assertions)
- `docs/step-07/B-SPEC.md` (B's design spec derived from A-CONSTRAINTS)
- `docs/DESIGN.md` §3.3, §7.2.7, §8 (architecture principles)
- `upstream-reference/rudder/server/src/routes/orgs.ts` line 584-624 (PATCH /:orgId behavioral reference)
- `upstream-reference/rudder/server/src/services/orgs.ts` update() method (transaction boundary reference)

## 2. Route Surface

| Method | Path | Step | Purpose |
|---|---|---|---|
| GET | /api/orgs | 6 | Board-scoped list, returns OrganizationSummary[] |
| GET | /api/orgs/{orgId} | 6 | Lookup-then-ownership, returns OrganizationDetail |
| PATCH | /api/orgs/{orgId} | 7 | Board+ownership-guarded update of 6 whitelisted fields, returns OrganizationDetail |

## 3. Layer Wiring Map

| Layer | File | Responsibility added in Step 7 |
|---|---|---|
| route | server/routes/orgs.py | PATCH handler + require_board_access guard + _extract_actor_identity helper |
| dependency | server/dependencies/orgs.py | get_owned_org_detail unchanged from Step 6 |
| dependency | server/dependencies/ownership.py | assert_organization_owned unchanged from Step 5 |
| dependency | server/dependencies/database.py | get_session wraps async with session.begin() — refactor |
| service | server/services/orgs.py | ORG_UPDATE_TO_COLUMN map + OrgService.update method |
| query | packages/database/queries/organizations.py | update_organization helper |
| query | packages/database/queries/activity_log.py | insert_activity_log helper — new file |
| schema | packages/database/schema/ | unchanged |

## 4. Error Code Matrix

| Order | Layer | Condition | Status | Detail substring |
|---|---|---|---|---|
| 1 | require_board_access | actor missing | 503 | Actor context |
| 2 | require_board_access | actor.type != board | 403 | Board access required |
| 3 | get_owned_org_detail SELECT | org not found | 404 | Organization not found |
| 4 | assert_organization_owned | no ownership row | 403 | no ownership record |
| 5 | assert_organization_owned | ownership owned by another pod | 403 | another pod |
| 6 | assert_organization_owned | lease expired | 409 | expired |
| 7 | validate_update_organization | payload invalid | 422 | validator ValueError string |

## 5. Activity Log Semantics

Fixed for Step 7 first batch:

| Field | Value |
|---|---|
| org_id | path {orgId} |
| action | "organization.updated" |
| entity_type | "organization" |
| entity_id | path {orgId} |
| actor_type | from _extract_actor_identity |
| actor_id | from _extract_actor_identity |
| agent_id | None |
| run_id | None |
| details | dict(payload) — raw camelCase |
| created_at | server default now() |

Atomicity: row inserted inside the same request-scoped transaction as the UPDATE.

Empty payload special case: no UPDATE, no activity row, returns current detail.

## 6. Transaction Restructure Note

get_session was lifted to request-scoped transaction (`async with session.begin()`). The previous version opened the session but no transaction, leaving sqlalchemy to autobegin on the first SELECT. The collision happened when get_owned_org_detail's SELECT autobegan, and then service.update tried to open its own async with session.begin() for the update + activity pair — sqlalchemy raised InvalidRequestError: A transaction is already begun on this Session. With the dependency-level transaction, the entire request runs in one explicit tx and the service no longer needs to open a nested one.

Test fixtures using async_transaction(session) are unaffected because they create sessions via session_factory() directly, not via get_session.

## 7. Test Coverage Mapping

A-CONSTRAINTS §12 13 required assertions (12 test functions; row 13 is transitive):

| # | Assertion | Test |
|---|---|---|
| 1 | organization list board request success | test_org_list_board_success |
| 2 | organization list missing actor returns 503 | test_org_list_missing_actor_returns_503 |
| 3 | organization list non-board rejected with 403 | test_org_list_non_board_returns_403 |
| 4 | organization detail owned request success | test_org_detail_owned_returns_200 |
| 5 | organization detail missing resource returns 404 | test_org_detail_missing_returns_404 |
| 6 | organization update owned + board success | test_org_update_owned_board_returns_200 |
| 7 | organization update can change config fields | test_org_update_changes_config_fields |
| 8 | organization update foreign ownership rejected | test_org_update_foreign_returns_403 |
| 9 | organization update expired ownership rejected | test_org_update_expired_returns_409 |
| 10 | organization update non-board rejected | test_org_update_non_board_returns_403 |
| 11 | organization update invalid payload returns 422 | test_org_update_invalid_payload_returns_422 |
| 12 | organization update writes minimal activity record | test_org_update_writes_activity_record |
| 13 | response field names use shared camelCase | covered transitively by tests 4, 6, 7 |

5 supplementary tests:

| Test | Defends |
|---|---|
| test_org_update_partial_does_not_touch_other_fields | A §7.2 update 只改变 payload 中显式提供的字段 |
| test_org_update_missing_actor_returns_503 | A §7.4 503 for PATCH path |
| test_org_update_missing_org_returns_404 | A §7.4 404 for PATCH path |
| test_org_update_missing_ownership_returns_403 | A §7.4 missing ownership distinct from foreign |
| test_org_update_empty_payload_no_activity | A §7.3 no-op must not write audit |

Total tests added in Step 7: 21 (3 query-level in Task 1 + 1 query-level in Task 2 + 17 contract in Task 5). Combined with Step 1-6 baseline (74): 95 passed.

## 8. Upstream Cross-Check

Preserved from rudder/server/src/routes/orgs.ts PATCH /:orgId:
- HTTP method + path
- Body validation precedes service call
- Service returns null then 404 with "Organization not found"
- Activity log written with action "organization.updated", entity_type "organization", entity_id orgId, details body
- Actor identity from request context not body

Deviations and why:

| Upstream | Octopus | Reason |
|---|---|---|
| updateOrganizationSchema for board, updateOrganizationBrandingSchema for agent CEO | validate_update_organization for board only | Step 7 first batch is board-only; agent branding deferred |
| assertCompanyAccess based on req.actor.orgIds membership | assert_organization_owned based on OrganizationOwnership.pod_id | Octopus uses pod-level ownership per DESIGN.md §6.3 |
| In-route assertBoard after access check | Standalone require_board_access dependency runs before ownership | FastAPI dependency injection wants non-DB checks first |
| Activity logged after service call returns | Activity logged inside service same tx as UPDATE | Atomic audit — upstream uses separate await, Octopus uses single tx |
| logoAssetId handling, branding, workspaceConfig | Not in Step 7 scope | Per A §3 §6.2 |

## 9. Known Gaps

- Production app has no actor injection middleware. Real curl against the production server returns 503 on every org endpoint. Tracked for resolution in a later step (DESIGN.md §6.5 and §7.2.6 describe what is required).
- tests/workflows/ end-to-end harness still not created in this project.
- Org create / delete / archive sub-routes intentionally deferred per A §3.

## 10. Verification Record

Four-step verification after final commit:

```
.venv\Scripts\ruff.exe check . --fix       → All checks passed!
.venv\Scripts\ruff.exe format .            → N files left unchanged
.venv\Scripts\python.exe -m pytest -q      → 95 passed
.venv\Scripts\python.exe -m pyright --pythonpath .venv\Scripts\python.exe → 0 errors
```

Manual HTTP smoke against production app: all three org endpoints return 503 — known gap documented in §9.
```

Replace the placeholder count `N` with the actual number ruff reports.

- [ ] **Step 2: Run pytest one more time as a no-op safety**

```powershell
.venv\Scripts\python.exe -m pytest -q
```

Expected: 95 passed (unchanged from Task 5).

- [ ] **Step 3: Commit**

```powershell
git add docs/step-07/ORGANIZATION-MANAGEMENT.md
git commit -m "docs(step-07): record organization management execution and gaps"
```

---

## Self-Review

**Spec coverage (B-SPEC.md sections):**

| Spec section | Plan task |
|---|---|
| §1 Motivation | n/a — informational |
| §2 Contract sources | Pre-requisites + Task 1-5 reference inputs explicitly |
| §3 Scope | Task 5 implements in-scope; out-of-scope items intentionally absent |
| §4 Architecture | Tasks 1-5 follow the 4-layer diagram bottom-up |
| §4 Key design decision (request-scoped tx) | Task 3 |
| §5.1 update_organization | Task 1 |
| §5.2 insert_activity_log | Task 2 |
| §5.3 get_session refactor | Task 3 |
| §5.4 OrgService.update | Task 4 |
| §5.5 PATCH route + _extract_actor_identity | Task 5 |
| §6 Data flow | Implicit in Task 5 dependency wiring |
| §7 Error code matrix | Reproduced in Task 5 Step 3 |
| §8 Activity log semantics | Implemented in Task 4 service.update; documented in Task 6 §5 |
| §9 Frozen field whitelist | ORG_UPDATE_TO_COLUMN in Task 4 |
| §10.1-10.3 Test strategy | Task 5 Step 1 |
| §11 Verification procedure | After every task |
| §12 Upstream cross-check | Task 6 §8 |
| §13 Acceptance criteria | Implicit completion criterion for Task 6 |
| §14 Deferred items | Task 6 §9 |

**Placeholder scan:** none — every step has runnable PowerShell commands, complete code blocks, and expected outcomes. The single `N` in Task 6 Step 1 ruff result is explicitly called out as "replace with actual number".

**Type consistency check:**
- `update_organization(session, organization_id, fields)` — same signature in Task 1 (def) and Task 4 (caller)
- `insert_activity_log(session, *, org_id, actor_type, actor_id, action, entity_type, entity_id, agent_id=None, run_id=None, details=None)` — same signature in Task 2 (def) and Task 4 (caller)
- `OrgService.update(org_id, payload, *, actor_type, actor_id)` — same signature in Task 4 (def) and Task 5 (route caller)
- `OrganizationDetail` returned by `_to_detail` (Task 4) consumed unchanged by both `get_org` and `update_org` routes (Task 5)
- `ORG_UPDATE_TO_COLUMN` whitelist matches B-SPEC §9 exactly: name, description, budgetMonthlyCents, defaultChatIssueCreationMode, brandColor, requireBoardApprovalForNewAgents
- Error detail substrings in Task 5 route source match assertions in Task 5 test source: "Actor context", "Board access required", "Organization not found", "no ownership record", "another pod", "expired", "budgetMonthlyCents"

**Layer hard constraint compliance (B-SPEC §4 → A §8):**
- server/routes calls dependencies + validator + service only ✓
- server/services receives session via __init__, never creates one ✓
- packages/database/queries return ORM rows, never DTOs ✓
- Board access + ownership in dependency/route layer ✓
- Validator only in shared layer ✓
- Activity log written via query helper called from service, never from route ✓

---

## Execution Handoff

Plan complete and saved to `docs/step-07/B-PLAN.md`. Two execution options:

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
