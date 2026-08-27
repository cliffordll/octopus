from __future__ import annotations

import shutil
from collections.abc import Generator
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_octopus_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[None, None, None]:
    octopus_home = tmp_path / "octopus-home"
    monkeypatch.setenv("OCTOPUS_HOME", str(octopus_home))
    monkeypatch.setenv("OCTOPUS_INSTANCE_ID", "test")
    monkeypatch.setenv("OCTOPUS_LOCAL_TRUSTED", "0")
    try:
        yield
    finally:
        shutil.rmtree(octopus_home, ignore_errors=True)
