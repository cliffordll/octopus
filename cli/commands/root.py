from __future__ import annotations

import argparse
import asyncio
from getpass import getpass

from packages.database.clients import (
    async_write_transaction,
    create_database_engine,
    create_session_factory,
)
from packages.database.migrations.runner import upgrade_to_head
from server.auth.root_provisioning import RootProvisioningService
from server.config import load_settings

from ..client import ApiClient


def configure(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("root", help="Manage the instance root account")
    actions = parser.add_subparsers(dest="root_action", required=True)
    create_parser = actions.add_parser("create", help="Create a root account")
    create_parser.add_argument("--name", required=True)
    create_parser.add_argument("--email", required=True)
    create_parser.set_defaults(handler=create_root)


def create_root(args: argparse.Namespace, _api: ApiClient) -> dict[str, str]:
    password = getpass("Root password: ")
    return asyncio.run(
        _create_root(name=args.name, email=args.email, password=password)
    )


async def _create_root(*, name: str, email: str, password: str) -> dict[str, str]:
    settings = load_settings()
    await upgrade_to_head(settings.database_url)
    engine = create_database_engine(settings.database_url)
    try:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            async with async_write_transaction(session):
                user_id = await RootProvisioningService(session).create(
                    name=name, email=email, password=password
                )
        return {"id": user_id, "email": email.strip().lower(), "role": "root"}
    finally:
        await engine.dispose()
