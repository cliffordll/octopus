from __future__ import annotations

import argparse
from typing import Any

from ..client import ApiClient


def configure(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("chat", help="Manage agent chats")
    actions = parser.add_subparsers(dest="chat_action", required=True)
    list_parser = actions.add_parser("list")
    list_parser.add_argument("--org-id", required=True)
    list_parser.set_defaults(handler=list_chats)
    get_parser = actions.add_parser("get")
    get_parser.add_argument("chat_id")
    get_parser.set_defaults(handler=get_chat)
    create_parser = actions.add_parser("create")
    create_parser.add_argument("--org-id", required=True)
    create_parser.add_argument("--title", required=True)
    create_parser.add_argument("--agent-id")
    create_parser.set_defaults(handler=create_chat)
    messages_parser = actions.add_parser("messages")
    messages_parser.add_argument("chat_id")
    messages_parser.set_defaults(handler=list_messages)
    message_parser = actions.add_parser("message")
    message_parser.add_argument("chat_id")
    message_parser.add_argument("--body", required=True)
    message_parser.set_defaults(handler=add_message)


def list_chats(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/orgs/{args.org_id}/chats")


def get_chat(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/chats/{args.chat_id}")


def create_chat(args: argparse.Namespace, client: ApiClient) -> Any:
    payload: dict[str, str] = {"title": args.title}
    if args.agent_id:
        payload["preferredAgentId"] = args.agent_id
    return client.request("POST", f"/api/orgs/{args.org_id}/chats", json=payload)


def list_messages(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/chats/{args.chat_id}/messages")


def add_message(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request(
        "POST", f"/api/chats/{args.chat_id}/messages", json={"body": args.body}
    )
