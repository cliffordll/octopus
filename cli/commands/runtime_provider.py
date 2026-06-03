from __future__ import annotations

import argparse
import json
from typing import Any
from urllib.parse import quote

from ..client import ApiClient


def configure(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "runtime-provider", help="Manage runtime providers and models"
    )
    actions = parser.add_subparsers(dest="runtime_provider_action", required=True)

    list_parser = actions.add_parser("list", help="List runtime providers")
    _add_org_runtime_args(list_parser)
    list_parser.set_defaults(handler=list_providers)

    create_parser = actions.add_parser("create", help="Create a runtime provider")
    _add_org_runtime_args(create_parser)
    _add_provider_fields(create_parser, require_identity=True)
    create_parser.set_defaults(handler=create_provider)

    update_parser = actions.add_parser("update", help="Update a runtime provider")
    _add_org_runtime_args(update_parser)
    update_parser.add_argument("--provider-id", required=True)
    _add_provider_fields(
        update_parser, require_identity=False, include_provider_id=False
    )
    update_parser.set_defaults(handler=update_provider)

    delete_parser = actions.add_parser("delete", help="Delete a runtime provider")
    _add_org_runtime_args(delete_parser)
    delete_parser.add_argument("--provider-id", required=True)
    delete_parser.set_defaults(handler=delete_provider)

    models_parser = actions.add_parser("models", help="List runtime models")
    _add_org_runtime_args(models_parser)
    models_parser.add_argument("--provider-id", required=True)
    models_parser.set_defaults(handler=list_models)

    model_create_parser = actions.add_parser(
        "model-create", help="Create a runtime model"
    )
    _add_org_runtime_args(model_create_parser)
    _add_model_fields(model_create_parser, require_identity=True)
    model_create_parser.set_defaults(handler=create_model)

    model_update_parser = actions.add_parser(
        "model-update", help="Update a runtime model"
    )
    _add_org_runtime_args(model_update_parser)
    _add_model_fields(model_update_parser, require_identity=True)
    model_update_parser.set_defaults(handler=update_model)

    model_delete_parser = actions.add_parser(
        "model-delete", help="Delete a runtime model"
    )
    _add_org_runtime_args(model_delete_parser)
    model_delete_parser.add_argument("--provider-id", required=True)
    model_delete_parser.add_argument("--model-id", required=True)
    model_delete_parser.set_defaults(handler=delete_model)


def _add_org_runtime_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--org-id", required=True)
    parser.add_argument("--runtime-type", required=True)


def _add_provider_fields(
    parser: argparse.ArgumentParser,
    *,
    require_identity: bool,
    include_provider_id: bool = True,
) -> None:
    if include_provider_id:
        parser.add_argument("--provider-id", required=require_identity)
    parser.add_argument("--name")
    parser.add_argument("--protocol")
    parser.add_argument("--base-url")
    parser.add_argument("--api-key")
    parser.add_argument("--api-key-env")
    parser.add_argument("--enabled", action="store_true")
    parser.add_argument("--disabled", action="store_true")
    parser.add_argument("--options-json")
    parser.add_argument("--metadata-json")


def _add_model_fields(
    parser: argparse.ArgumentParser, *, require_identity: bool
) -> None:
    parser.add_argument("--provider-id", required=True)
    parser.add_argument("--model-id", required=require_identity)
    parser.add_argument("--display-name")
    parser.add_argument("--enabled", action="store_true")
    parser.add_argument("--disabled", action="store_true")
    parser.add_argument("--metadata-json")


def _json_object(value: str | None) -> dict[str, Any] | None:
    if value is None:
        return None
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("JSON value must be an object.")
    return parsed


def _enabled_value(args: argparse.Namespace) -> bool | None:
    if args.enabled and args.disabled:
        raise ValueError("--enabled and --disabled cannot both be set.")
    if args.enabled:
        return True
    if args.disabled:
        return False
    return None


def _provider_payload(
    args: argparse.Namespace, *, include_identity: bool
) -> dict[str, Any]:
    payload = {
        key: value
        for key, value in {
            "runtimeType": args.runtime_type if include_identity else None,
            "providerId": args.provider_id if include_identity else None,
            "name": args.name,
            "protocol": args.protocol,
            "baseUrl": args.base_url,
            "apiKey": args.api_key,
            "apiKeyEnv": args.api_key_env,
            "enabled": _enabled_value(args),
            "options": _json_object(args.options_json),
            "metadata": _json_object(args.metadata_json),
        }.items()
        if value is not None
    }
    if not payload:
        raise ValueError("At least one provider field is required.")
    return payload


def _model_payload(
    args: argparse.Namespace, *, include_identity: bool
) -> dict[str, Any]:
    payload = {
        key: value
        for key, value in {
            "modelId": args.model_id if include_identity else None,
            "displayName": args.display_name,
            "enabled": _enabled_value(args),
            "metadata": _json_object(args.metadata_json),
        }.items()
        if value is not None
    }
    if not payload:
        raise ValueError("At least one model field is required.")
    return payload


def _provider_root(args: argparse.Namespace) -> str:
    return f"/api/orgs/{args.org_id}/runtime-providers"


def _provider_detail(args: argparse.Namespace) -> str:
    return f"{_provider_root(args)}/{args.provider_id}"


def _model_root(args: argparse.Namespace) -> str:
    return f"{_provider_detail(args)}/models"


def _model_detail(args: argparse.Namespace) -> str:
    return f"{_model_root(args)}/{quote(args.model_id, safe='')}"


def _runtime_params(args: argparse.Namespace) -> dict[str, str]:
    return {"runtimeType": args.runtime_type}


def list_providers(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", _provider_root(args), params=_runtime_params(args))


def create_provider(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request(
        "POST",
        _provider_root(args),
        json=_provider_payload(args, include_identity=True),
    )


def update_provider(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request(
        "PATCH",
        _provider_detail(args),
        params=_runtime_params(args),
        json=_provider_payload(args, include_identity=False),
    )


def delete_provider(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request(
        "DELETE", _provider_detail(args), params=_runtime_params(args)
    )


def list_models(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("GET", _model_root(args), params=_runtime_params(args))


def create_model(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request(
        "POST",
        _model_root(args),
        params=_runtime_params(args),
        json=_model_payload(args, include_identity=True),
    )


def update_model(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request(
        "PATCH",
        _model_detail(args),
        params=_runtime_params(args),
        json=_model_payload(args, include_identity=False),
    )


def delete_model(args: argparse.Namespace, client: ApiClient) -> Any:
    return client.request("DELETE", _model_detail(args), params=_runtime_params(args))
