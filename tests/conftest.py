"""Shared fixtures.

Every test runs against a temporary configuration home, so the real
``~/.config/restpilot`` is never read or written.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from restpilot.config import ConfigPaths
from restpilot.environments.manager import EnvironmentManager
from restpilot.models import OpenAPIDocument
from restpilot.openapi.loader import load_spec
from restpilot.openapi.parser import parse_spec, save_document

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "examples"
EXAMPLE_SPEC = EXAMPLES_DIR / "openapi.yaml"

_ISOLATED_ENV_VARS = (
    "RESTPILOT_TOKEN",
    "RESTPILOT_BASE_URL",
    "RESTPILOT_STAGE_KEY",
    "XDG_CONFIG_HOME",
)


def output_of(result: Result) -> str:
    """Return stdout and stderr of a CLI run, whatever the runner separates."""
    text = result.stdout or ""
    with contextlib.suppress(ValueError, AttributeError):
        text += result.stderr or ""
    return text


@pytest.fixture(autouse=True)
def project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Isolate configuration and the working directory for every test."""
    config_home = tmp_path / "config"
    working_dir = tmp_path / "project"
    working_dir.mkdir(parents=True)
    monkeypatch.setenv("RESTPILOT_CONFIG_HOME", str(config_home))
    for name in _ISOLATED_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(working_dir)
    yield working_dir


@pytest.fixture
def paths() -> ConfigPaths:
    """The configuration paths discovered from the isolated working directory."""
    return ConfigPaths.discover()


@pytest.fixture
def manager(paths: ConfigPaths) -> EnvironmentManager:
    """An environment manager bound to the isolated configuration."""
    return EnvironmentManager(paths)


@pytest.fixture
def local_env(manager: EnvironmentManager) -> EnvironmentManager:
    """A manager with a ready-to-use ``local`` environment."""
    manager.create(
        "local",
        base_url="http://testserver",
        headers={"Accept": "application/json"},
    )
    manager.use("local")
    return manager


@pytest.fixture
def example_spec() -> Path:
    """Path to the OpenAPI document shipped in ``examples/``."""
    return EXAMPLE_SPEC


@pytest.fixture
def document(example_spec: Path) -> OpenAPIDocument:
    """The parsed example specification."""
    return parse_spec(load_spec(str(example_spec)), source=str(example_spec))


@pytest.fixture
def imported_spec(paths: ConfigPaths, document: OpenAPIDocument) -> OpenAPIDocument:
    """The example specification, already imported into the isolated config."""
    save_document(paths.spec_path, document)
    return document


@pytest.fixture
def runner() -> CliRunner:
    """A Typer CLI runner."""
    return CliRunner()
