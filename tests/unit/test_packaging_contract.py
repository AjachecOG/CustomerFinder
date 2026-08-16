"""Release packaging contracts that should not regress silently."""

from __future__ import annotations

import tomllib
from importlib import resources
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_runtime_dependencies_are_api_free_and_browser_free() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    dependencies = [str(item).lower() for item in project["dependencies"]]
    forbidden = ("google", "playwright", "selenium", "pydantic-settings", "python-dotenv")

    assert project["requires-python"] == ">=3.12,<3.13"
    assert all(not any(name in dependency for name in forbidden) for dependency in dependencies)


def test_release_files_and_packaged_gui_exist() -> None:
    assert (ROOT / "LICENSE").is_file()
    assert (ROOT / "ATTRIBUTION.md").is_file()
    assert resources.files("customer_finder.static").joinpath("calibration.html").is_file()


def test_release_contract_is_native_and_container_free() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert not (ROOT / "Dockerfile").exists()
    assert not (ROOT / "scripts" / "docker_smoke.ps1").exists()
    assert "Docker, WSL and Node.js are not required" in readme
