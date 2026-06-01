from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from ..client import ApiClient


def configure(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("asset", help="Read stored asset content")
    actions = parser.add_subparsers(dest="asset_action", required=True)
    content_parser = actions.add_parser("content")
    content_parser.add_argument("asset_id")
    content_parser.add_argument("--output")
    content_parser.set_defaults(handler=get_content)


def get_content(args: argparse.Namespace, client: ApiClient) -> Any:
    content = client.request_bytes("GET", f"/api/assets/{args.asset_id}/content")
    if args.output:
        output_path = Path(args.output)
        output_path.write_bytes(content)
        return {"output": str(output_path), "byteSize": len(content)}
    return {
        "content": content.decode("utf-8", errors="replace"),
        "byteSize": len(content),
    }
