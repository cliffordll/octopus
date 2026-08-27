from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "ui"


def run(command: Sequence[str], *, cwd: Path = ROOT) -> None:
    executable = shutil.which(command[0])
    if executable is None:
        raise FileNotFoundError(command[0])
    resolved_command = [executable, *command[1:]]
    display = " ".join(command)
    if cwd != ROOT:
        display = f"(cd {cwd.relative_to(ROOT)} && {display})"
    print(f"\n$ {display}", flush=True)
    subprocess.run(resolved_command, cwd=cwd, check=True)


def has_ui_dependencies() -> bool:
    return (UI / "package.json").exists() and (UI / "node_modules").exists()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Octopus local CI checks.")
    parser.add_argument(
        "--pre-commit",
        action="store_true",
        help="Run the commit gate. Uses format --check so commits never hide formatting changes.",
    )
    parser.add_argument(
        "--skip-ui",
        action="store_true",
        help="Skip UI typecheck/tests.",
    )
    args = parser.parse_args(argv)

    try:
        if args.pre_commit:
            run(["uv", "run", "ruff", "format", "--check", "."])
        else:
            run(["uv", "run", "ruff", "format", "."])
            run(["uv", "run", "ruff", "format", "--check", "."])
        run(["uv", "run", "ruff", "check", "."])
        run(["uv", "run", "pyright", "."])
        run(["uv", "run", "pytest"])

        if not args.skip_ui:
            if has_ui_dependencies():
                run(["npm", "run", "typecheck"], cwd=UI)
                run(["npm", "test"], cwd=UI)
            else:
                print(
                    "\nSkipping UI checks because ui/node_modules is missing. "
                    "Run `cd ui && npm install` or use `--skip-ui` intentionally.",
                    flush=True,
                )
                if args.pre_commit:
                    return 1
    except subprocess.CalledProcessError as exc:
        return exc.returncode
    except FileNotFoundError as exc:
        print(f"Missing command: {exc.filename}", file=sys.stderr)
        return 127
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
