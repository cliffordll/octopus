from __future__ import annotations

import argparse
import json
from typing import Any

from ..client import ApiClient


def configure(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("chat", help="Manage agent chats")
    actions = parser.add_subparsers(dest="chat_action", required=True)
    list_parser = actions.add_parser("list")
    list_parser.add_argument("--org-id", required=True)
    list_parser.add_argument("--status", default="active")
    list_parser.add_argument("--q")
    list_parser.set_defaults(handler=list_chats)
    get_parser = actions.add_parser("get")
    get_parser.add_argument("chat_id")
    get_parser.set_defaults(handler=get_chat)
    create_parser = actions.add_parser("create")
    create_parser.add_argument("--org-id", required=True)
    create_parser.add_argument("--title", required=True)
    create_parser.add_argument("--agent-id")
    create_parser.add_argument("--summary")
    create_parser.add_argument("--issue-creation-mode")
    create_parser.add_argument("--plan-mode", action="store_true")
    create_parser.add_argument("--context-link", action="append", default=[])
    create_parser.set_defaults(handler=create_chat)
    update_parser = actions.add_parser("update")
    update_parser.add_argument("chat_id")
    update_parser.add_argument("--title")
    update_parser.add_argument("--summary")
    update_parser.add_argument("--agent-id")
    update_parser.add_argument("--status")
    update_parser.add_argument("--issue-creation-mode")
    update_parser.add_argument("--plan-mode", action="store_true")
    update_parser.add_argument("--no-plan-mode", action="store_true")
    update_parser.set_defaults(handler=update_chat)
    user_state_parser = actions.add_parser("user-state")
    user_state_parser.add_argument("chat_id")
    user_state_parser.add_argument("--pinned", action="store_true")
    user_state_parser.add_argument("--unpinned", action="store_true")
    user_state_parser.add_argument("--unread", action="store_true")
    user_state_parser.add_argument("--read", action="store_true")
    user_state_parser.set_defaults(handler=update_user_state)
    context_parser = actions.add_parser("context-link")
    context_parser.add_argument("chat_id")
    context_parser.add_argument("--entity-type", required=True)
    context_parser.add_argument("--entity-id", required=True)
    context_parser.add_argument("--metadata")
    context_parser.set_defaults(handler=add_context_link)
    project_parser = actions.add_parser("project-context")
    project_parser.add_argument("chat_id")
    project_parser.add_argument("--project-id")
    project_parser.set_defaults(handler=set_project_context)
    messages_parser = actions.add_parser("messages")
    messages_parser.add_argument("chat_id")
    messages_parser.set_defaults(handler=list_messages)
    message_parser = actions.add_parser("message")
    message_parser.add_argument("chat_id")
    message_parser.add_argument("--body", required=True)
    message_parser.add_argument("--edit-user-message-id")
    message_parser.set_defaults(handler=add_message)
    stream_parser = actions.add_parser("stream")
    stream_parser.add_argument("chat_id")
    stream_parser.add_argument("--body", required=True)
    stream_parser.add_argument("--edit-user-message-id")
    stream_parser.set_defaults(handler=stream_message)
    stream_stop_parser = actions.add_parser("stream-stop")
    stream_stop_parser.add_argument("chat_id")
    stream_stop_parser.set_defaults(handler=stop_stream)
    convert_parser = actions.add_parser("convert-to-issue")
    convert_parser.add_argument("chat_id")
    convert_parser.add_argument("--message-id")
    convert_parser.add_argument("--proposal")
    convert_parser.set_defaults(handler=convert_to_issue)
    resolve_parser = actions.add_parser("resolve-operation")
    resolve_parser.add_argument("chat_id")
    resolve_parser.add_argument("message_id")
    resolve_parser.add_argument(
        "--action", required=True, choices=["approve", "reject", "requestRevision"]
    )
    resolve_parser.add_argument("--note")
    resolve_parser.set_defaults(handler=resolve_operation)


def list_chats(args: argparse.Namespace, client: ApiClient) -> Any:
    params: dict[str, str] = {"status": args.status}
    if args.q:
        params["q"] = args.q
    return client.request("GET", f"/api/orgs/{args.org_id}/chats", params=params)


def get_chat(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/chats/{args.chat_id}")


def create_chat(args: argparse.Namespace, client: ApiClient) -> Any:
    payload: dict[str, Any] = {"title": args.title}
    if args.agent_id:
        payload["preferredAgentId"] = args.agent_id
    if args.summary is not None:
        payload["summary"] = args.summary
    if args.issue_creation_mode is not None:
        payload["issueCreationMode"] = args.issue_creation_mode
    if args.plan_mode:
        payload["planMode"] = True
    if args.context_link:
        payload["contextLinks"] = [
            _parse_context_link(value) for value in args.context_link
        ]
    return client.request("POST", f"/api/orgs/{args.org_id}/chats", json=payload)


def update_chat(args: argparse.Namespace, client: ApiClient) -> Any:
    payload: dict[str, Any] = {}
    if args.title is not None:
        payload["title"] = args.title
    if args.summary is not None:
        payload["summary"] = args.summary
    if args.agent_id is not None:
        payload["preferredAgentId"] = args.agent_id
    if args.status is not None:
        payload["status"] = args.status
    if args.issue_creation_mode is not None:
        payload["issueCreationMode"] = args.issue_creation_mode
    if args.plan_mode:
        payload["planMode"] = True
    if args.no_plan_mode:
        payload["planMode"] = False
    return client.request("PATCH", f"/api/chats/{args.chat_id}", json=payload)


def update_user_state(args: argparse.Namespace, client: ApiClient) -> Any:
    payload: dict[str, bool] = {}
    if args.pinned:
        payload["pinned"] = True
    if args.unpinned:
        payload["pinned"] = False
    if args.unread:
        payload["unread"] = True
    if args.read:
        payload["unread"] = False
    return client.request(
        "PATCH", f"/api/chats/{args.chat_id}/user-state", json=payload
    )


def add_context_link(args: argparse.Namespace, client: ApiClient) -> Any:
    payload: dict[str, Any] = {
        "entityType": args.entity_type,
        "entityId": args.entity_id,
    }
    if args.metadata:
        payload["metadata"] = _parse_json_object(args.metadata, "--metadata")
    return client.request(
        "POST", f"/api/chats/{args.chat_id}/context-links", json=payload
    )


def set_project_context(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request(
        "POST",
        f"/api/chats/{args.chat_id}/project-context",
        json={"projectId": args.project_id},
    )


def list_messages(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", f"/api/chats/{args.chat_id}/messages")


def add_message(args: argparse.Namespace, client: ApiClient) -> Any:
    payload: dict[str, Any] = {"body": args.body}
    if args.edit_user_message_id:
        payload["editUserMessageId"] = args.edit_user_message_id
    return client.request("POST", f"/api/chats/{args.chat_id}/messages", json=payload)


def stream_message(args: argparse.Namespace, client: ApiClient) -> Any:
    payload: dict[str, Any] = {"body": args.body}
    if args.edit_user_message_id:
        payload["editUserMessageId"] = args.edit_user_message_id
    return client.request(
        "POST", f"/api/chats/{args.chat_id}/messages/stream", json=payload
    )


def stop_stream(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request(
        "POST", f"/api/chats/{args.chat_id}/messages/stream/stop", json={}
    )


def convert_to_issue(args: argparse.Namespace, client: ApiClient) -> Any:
    payload: dict[str, Any] = {}
    if args.message_id:
        payload["messageId"] = args.message_id
    if args.proposal:
        payload["proposal"] = _parse_json_object(args.proposal, "--proposal")
    return client.request(
        "POST", f"/api/chats/{args.chat_id}/convert-to-issue", json=payload
    )


def resolve_operation(args: argparse.Namespace, client: ApiClient) -> Any:
    payload: dict[str, Any] = {"action": args.action}
    if args.note is not None:
        payload["decisionNote"] = args.note
    return client.request(
        "POST",
        f"/api/chats/{args.chat_id}/messages/{args.message_id}/operation-proposal/resolve",
        json=payload,
    )


def _parse_context_link(value: str) -> dict[str, Any]:
    if value.strip().startswith("{"):
        return _parse_json_object(value, "--context-link")
    parts = value.split(":", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise SystemExit("--context-link must be JSON or entityType:entityId")
    return {"entityType": parts[0], "entityId": parts[1]}


def _parse_json_object(value: str, flag: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{flag} must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise SystemExit(f"{flag} must be a JSON object")
    return parsed
