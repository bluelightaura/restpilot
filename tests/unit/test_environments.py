"""Environment manager behaviour."""

from __future__ import annotations

import stat

import pytest

from restpilot.config import ConfigPaths
from restpilot.exceptions import ConfigurationError, EnvironmentNotFoundError

pytestmark = pytest.mark.unit


def test_create_registers_and_selects_the_first_environment(manager):
    manager.create("local", base_url="http://localhost:8000")
    config = manager.load()
    assert config.environments["local"].base_url == "http://localhost:8000"
    assert config.current_environment == "local"


def test_create_strips_trailing_slash_from_base_url(manager):
    manager.create("local", base_url="http://localhost:8000/")
    assert manager.get("local").base_url == "http://localhost:8000"


def test_create_rejects_a_duplicate_without_force(manager):
    manager.create("local", base_url="http://localhost:8000")
    with pytest.raises(ConfigurationError) as error:
        manager.create("local", base_url="http://other:9000")
    assert "already exists" in error.value.message


def test_create_overwrites_with_force(manager):
    manager.create("local", base_url="http://localhost:8000")
    manager.create("local", base_url="http://other:9000", force=True)
    assert manager.get("local").base_url == "http://other:9000"


def test_create_rejects_an_invalid_base_url(manager):
    with pytest.raises(ConfigurationError) as error:
        manager.create("local", base_url="localhost:8000")
    assert "invalid environment" in error.value.message


def test_create_writes_an_owner_only_file(manager, paths):
    manager.create("local", base_url="http://localhost:8000")
    assert stat.S_IMODE(paths.global_config.stat().st_mode) == 0o600


def test_create_writes_to_the_local_file_when_requested(manager, project_dir):
    target = project_dir / ".restpilot.yaml"
    manager.create("local", base_url="http://localhost:8000", target=target)
    assert target.exists()
    discovered = ConfigPaths.discover().local_config
    assert discovered is not None
    assert "local" in discovered.read_text(encoding="utf-8")


def test_get_raises_for_an_unknown_environment(manager):
    manager.create("local", base_url="http://localhost:8000")
    with pytest.raises(EnvironmentNotFoundError) as error:
        manager.get("stage")
    assert error.value.message == "environment 'stage' does not exist."
    assert "local" in (error.value.hint or "")


def test_use_switches_the_current_environment(manager):
    manager.create("local", base_url="http://localhost:8000")
    manager.create("stage", base_url="https://stage.example.com")
    manager.use("stage")
    assert manager.current_name() == "stage"


def test_use_raises_for_an_unknown_environment(manager):
    with pytest.raises(EnvironmentNotFoundError):
        manager.use("stage")


def test_use_copies_an_inherited_environment_into_the_local_file(manager, project_dir):
    manager.create("stage", base_url="https://stage.example.com")
    local_manager_paths = project_dir / ".restpilot.yaml"
    local_manager_paths.write_text("environments: {}\n", encoding="utf-8")

    from restpilot.environments.manager import EnvironmentManager

    local_manager = EnvironmentManager(ConfigPaths.discover())
    local_manager.use("stage")
    assert local_manager.current_name() == "stage"
    assert "stage" in local_manager_paths.read_text(encoding="utf-8")


def test_delete_removes_the_environment_and_resets_the_selection(manager):
    manager.create("local", base_url="http://localhost:8000")
    manager.create("stage", base_url="https://stage.example.com")
    manager.use("local")
    manager.delete("local")
    config = manager.load()
    assert "local" not in config.environments
    assert config.current_environment == "stage"


def test_delete_raises_for_an_unknown_environment(manager):
    with pytest.raises(EnvironmentNotFoundError):
        manager.delete("ghost")


def test_list_environments_returns_every_definition(manager):
    manager.create("local", base_url="http://localhost:8000")
    manager.create("stage", base_url="https://stage.example.com")
    assert set(manager.list_environments()) == {"local", "stage"}


def test_resolve_substitutes_environment_variables(manager, monkeypatch):
    monkeypatch.setenv("RESTPILOT_TOKEN", "super-secret-value")
    manager.create(
        "local",
        base_url="http://localhost:8000",
        headers={"Authorization": "Bearer ${RESTPILOT_TOKEN}"},
    )
    name, environment = manager.resolve()
    assert name == "local"
    assert environment.headers["Authorization"] == "Bearer super-secret-value"


def test_resolve_reports_a_missing_variable(manager):
    manager.create(
        "local",
        base_url="http://localhost:8000",
        headers={"Authorization": "Bearer ${RESTPILOT_TOKEN}"},
    )
    with pytest.raises(ConfigurationError) as error:
        manager.resolve()
    assert "RESTPILOT_TOKEN" in error.value.message


def test_resolve_without_selection_explains_how_to_fix_it(manager):
    with pytest.raises(ConfigurationError) as error:
        manager.resolve()
    assert error.value.message == "no environment is selected."
    assert "env create" in (error.value.hint or "")


def test_resolve_accepts_an_explicit_name(manager):
    manager.create("local", base_url="http://localhost:8000")
    manager.create("stage", base_url="https://stage.example.com")
    name, environment = manager.resolve("stage")
    assert (name, environment.base_url) == ("stage", "https://stage.example.com")


def test_resolve_raises_for_an_unknown_explicit_name(manager):
    manager.create("local", base_url="http://localhost:8000")
    with pytest.raises(EnvironmentNotFoundError):
        manager.resolve("stage")


def test_configuration_file_never_stores_a_plaintext_token(manager, paths, monkeypatch):
    monkeypatch.setenv("RESTPILOT_TOKEN", "super-secret-value")
    manager.create(
        "local",
        base_url="http://localhost:8000",
        headers={"Authorization": "Bearer ${RESTPILOT_TOKEN}"},
    )
    manager.resolve()
    assert "super-secret-value" not in paths.global_config.read_text(encoding="utf-8")
