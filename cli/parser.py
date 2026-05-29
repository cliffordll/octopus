from __future__ import annotations

import argparse

from .client import DEFAULT_API_BASE
from .commands import (
    agent,
    approval,
    chat,
    goal,
    heartbeat,
    issue,
    messenger,
    organization,
    project,
    run_intelligence,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m cli", description="Octopus board API client"
    )
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    parser.add_argument("--json", action="store_true", dest="json_mode")
    resources = parser.add_subparsers(dest="resource", required=True)
    organization.configure(resources)
    issue.configure(resources)
    approval.configure(resources)
    project.configure(resources)
    goal.configure(resources)
    agent.configure(resources)
    heartbeat.configure(resources)
    run_intelligence.configure(resources)
    chat.configure(resources)
    messenger.configure(resources)
    return parser
