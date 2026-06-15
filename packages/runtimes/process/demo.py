from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path


SAFE_ENV_KEYS = (
    "OCTOPUS_ORG_ID",
    "OCTOPUS_AGENT_ID",
    "OCTOPUS_RUN_ID",
    "OCTOPUS_ISSUE_ID",
    "OCTOPUS_PROJECT_ID",
)


def main() -> int:
    payload = {
        "message": "Octopus process runtime demo succeeded.",
        "timestamp": datetime.now(UTC).isoformat(),
        "cwd": str(Path.cwd()),
        "safeEnv": {
            key: value
            for key in SAFE_ENV_KEYS
            if (value := os.environ.get(key)) is not None
        },
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
