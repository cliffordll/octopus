from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
import json
import sys

from packages.database.clients import create_database_engine, create_session_factory
from server.config import load_settings
from server.services.run_repair import IssueRunRepairService


async def _run(issue_id: str, *, apply: bool) -> dict[str, object]:
    settings = load_settings()
    engine = create_database_engine(settings.database_url)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            async with session.begin():
                service = IssueRunRepairService(session)
                result = (
                    await service.repair(issue_id)
                    if apply
                    else await service.inspect(issue_id)
                )
        return result
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect or recover expired Runs for one Issue tree. Restart the server "
            "onto the same code version before using --apply."
        )
    )
    parser.add_argument("issue_id", help="Root Issue UUID")
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Apply evidence-based recovery after the server loads this code version. "
            "Without this flag the command is read-only."
        ),
    )
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(_run(args.issue_id, apply=args.apply))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
