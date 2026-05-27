from __future__ import annotations

import sys
from collections.abc import Sequence
from typing import TextIO

from .client import ApiClient, ApiError
from .output import write_output
from .parser import build_parser


def main(
    argv: Sequence[str] | None = None,
    *,
    client: ApiClient | None = None,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    args = build_parser().parse_args(argv)
    api = client or ApiClient(args.api_base)
    try:
        data = args.handler(args, api)
    except (ApiError, ValueError) as exc:
        stderr.write(f"Error: {exc}\n")
        return 1
    write_output(data, json_mode=args.json_mode, stream=stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
