from __future__ import annotations

from pathlib import Path


def test_windows_dev_script_checks_ports_and_cleans_up_children() -> None:
    script = Path("scripts/dev.ps1")

    assert script.is_file()
    content = script.read_text(encoding="utf-8")

    assert "Assert-PortAvailable" in content
    assert "Stop-ProcessTree" in content
    assert "Register-EngineEvent PowerShell.Exiting" in content
    assert "trap [System.Management.Automation.PipelineStoppedException]" in content
    assert "-WindowStyle Hidden" in content
    assert "-NoNewWindow" not in content
    assert "Stop-PortOwnerIfOctopus" in content
    assert '$env:OCTOPUS_HOME = Join-Path $RepoRoot ".octopus"' in content
    assert ".\\.venv\\Scripts\\python.exe -m server" in content
    assert "npm run dev" in content
