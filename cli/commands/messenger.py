from __future__ import annotations

import argparse
from typing import Any

from ..client import ApiClient


def configure(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("messenger", help="Read messenger threads")
    actions = parser.add_subparsers(dest="messenger_action", required=True)

    list_parser = actions.add_parser("threads")
    list_parser.add_argument("--org-id", required=True)
    list_parser.set_defaults(handler=list_threads)

    chat_parser = actions.add_parser("chat")
    chat_parser.add_argument("--org-id", required=True)
    chat_parser.add_argument("conversation_id")
    chat_parser.set_defaults(handler=get_chat_thread)

    read_parser = actions.add_parser("read")
    read_parser.add_argument("--org-id", required=True)
    read_parser.add_argument("thread_key")
    read_parser.add_argument("--last-read-at")
    read_parser.set_defaults(handler=mark_read)

    issues_parser = actions.add_parser("issues")
    issues_parser.add_argument("--org-id", required=True)
    issues_parser.set_defaults(handler=get_issues_thread)

    approvals_parser = actions.add_parser("approvals")
    approvals_parser.add_argument("--org-id", required=True)
    approvals_parser.set_defaults(handler=get_approvals_thread)

    system_parser = actions.add_parser("system")
    system_parser.add_argument("--org-id", required=True)
    system_parser.add_argument("thread_kind")
    system_parser.set_defaults(handler=get_system_thread)


def list_threads(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/orgs/{args.org_id}/messenger/threads")


def get_chat_thread(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request(
        "GET", f"/api/orgs/{args.org_id}/messenger/chat/{args.conversation_id}"
    )


def mark_read(args: argparse.Namespace, client: ApiClient) -> Any:
    payload = {"lastReadAt": args.last_read_at} if args.last_read_at else {}
    return client.request(
        "POST",
        f"/api/orgs/{args.org_id}/messenger/threads/{args.thread_key}/read",
        json=payload,
    )


def get_issues_thread(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/orgs/{args.org_id}/messenger/issues")


def get_approvals_thread(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/orgs/{args.org_id}/messenger/approvals")


def get_system_thread(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request(
        "GET", f"/api/orgs/{args.org_id}/messenger/system/{args.thread_kind}"
    )
