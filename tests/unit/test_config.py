"""Configuration discovery, precedence and validation."""

from __future__ import annotations

import pytest

from restpilot.config import (
    ConfigPaths,
    find_local_config,
    global_config_dir,
    load_config,
    merge_configs,
)
from restpilot.environments.storage import load_config_file, write_config
from restpilot.exceptions import ConfigurationError
from restpilot.models import ApplicationConfig, EnvironmentConfig

pytestmark = pytest.mark.unit

GLOBAL_YAML = """
current_environment: stage
environments:
  stage:
    base_url: https://stage.example.com
    timeout: 20
  local:
    base_url: http://global-local:9000
"""

LOCAL_YAML = """
current_environment: local
environments:
  local:
    base_url: http://localhost:8000
    headers:
      Accept: application/json
"""


def test_global_config_dir_honours_override(monkeypatch, tmp_path):
    monkeypatch.setenv("RESTPILOT_CONFIG_HOME", str(tmp_path / "cfg"))
    assert global_config_dir() == tmp_path / "cfg"


def test_global_config_dir_falls_back_to_xdg(monkeypatch, tmp_path):
    monkeypatch.delenv("RESTPILOT_CONFIG_HOME", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert global_config_dir() == tmp_path / "xdg" / "restpilot"


def test_global_config_dir_defaults_to_home(monkeypatch, tmp_path):
    monkeypatch.delenv("RESTPILOT_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr("pathlib.Path.home", classmethod(lambda cls: tmp_path))
    assert global_config_dir() == tmp_path / ".config" / "restpilot"


def test_yaml_configuration_is_loaded(paths):
    paths.global_config.parent.mkdir(parents=True, exist_ok=True)
    paths.global_config.write_text(GLOBAL_YAML, encoding="utf-8")
    config = load_config(paths)
    assert config.current_environment == "stage"
    assert config.environments["stage"].timeout == 20


def test_local_configuration_takes_precedence(project_dir):
    global_config = ConfigPaths.discover().global_config
    global_config.parent.mkdir(parents=True, exist_ok=True)
    global_config.write_text(GLOBAL_YAML, encoding="utf-8")
    (project_dir / ".restpilot.yaml").write_text(LOCAL_YAML, encoding="utf-8")

    config = load_config(ConfigPaths.discover())
    assert config.current_environment == "local"
    assert config.environments["local"].base_url == "http://localhost:8000"
    assert config.environments["stage"].base_url == "https://stage.example.com"


def test_local_config_is_found_in_parent_directory(project_dir):
    (project_dir / ".restpilot.yaml").write_text(LOCAL_YAML, encoding="utf-8")
    nested = project_dir / "tests" / "api"
    nested.mkdir(parents=True)
    assert find_local_config(nested) == project_dir / ".restpilot.yaml"


def test_find_local_config_returns_none_when_absent(project_dir):
    assert find_local_config(project_dir) is None


def test_spec_path_is_project_local_when_local_config_exists(project_dir):
    (project_dir / ".restpilot.yaml").write_text(LOCAL_YAML, encoding="utf-8")
    paths = ConfigPaths.discover()
    assert paths.spec_path == project_dir / ".restpilot" / "api.json"
    assert paths.write_target == project_dir / ".restpilot.yaml"
    assert paths.generated_tests_dir == project_dir / "generated_tests"


def test_spec_path_falls_back_to_global_directory(paths, project_dir):
    assert paths.local_config is None
    assert paths.spec_path == paths.global_config.parent / "api.json"
    assert paths.generated_tests_dir == project_dir / "generated_tests"


def test_merge_configs_prefers_the_override():
    base = ApplicationConfig(
        current_environment="stage",
        environments={"stage": EnvironmentConfig(base_url="https://stage.example.com")},
    )
    override = ApplicationConfig(
        environments={"local": EnvironmentConfig(base_url="http://localhost:8000")}
    )
    merged = merge_configs(base, override)
    assert merged.current_environment == "stage"
    assert set(merged.environments) == {"stage", "local"}


def test_invalid_yaml_raises_configuration_error(paths):
    paths.global_config.parent.mkdir(parents=True, exist_ok=True)
    paths.global_config.write_text("environments: [unclosed", encoding="utf-8")
    with pytest.raises(ConfigurationError) as error:
        load_config(paths)
    assert "not valid YAML" in error.value.message


def test_non_mapping_yaml_raises_configuration_error(paths):
    paths.global_config.parent.mkdir(parents=True, exist_ok=True)
    paths.global_config.write_text("- one\n- two\n", encoding="utf-8")
    with pytest.raises(ConfigurationError):
        load_config(paths)


def test_unknown_configuration_keys_are_rejected(paths):
    paths.global_config.parent.mkdir(parents=True, exist_ok=True)
    paths.global_config.write_text("nonsense: true\n", encoding="utf-8")
    with pytest.raises(ConfigurationError) as error:
        load_config(paths)
    assert "invalid configuration" in error.value.message


def test_missing_config_file_yields_empty_configuration(paths):
    assert load_config(paths).environments == {}


def test_empty_config_file_yields_empty_configuration(paths):
    paths.global_config.parent.mkdir(parents=True, exist_ok=True)
    paths.global_config.write_text("", encoding="utf-8")
    assert load_config_file(paths.global_config).environments == {}


def test_written_configuration_round_trips(paths):
    config = ApplicationConfig(
        current_environment="local",
        environments={
            "local": EnvironmentConfig(
                base_url="http://localhost:8000",
                headers={"Authorization": "Bearer ${RESTPILOT_TOKEN}"},
            )
        },
    )
    write_config(paths.global_config, config)
    reloaded = load_config_file(paths.global_config)
    assert reloaded == config
    assert "${RESTPILOT_TOKEN}" in paths.global_config.read_text(encoding="utf-8")


def test_whole_second_timeouts_are_written_as_integers(paths):
    config = ApplicationConfig(
        environments={"local": EnvironmentConfig(base_url="http://localhost:8000", timeout=10)}
    )
    write_config(paths.global_config, config)
    assert "timeout: 10\n" in paths.global_config.read_text(encoding="utf-8")


def test_fractional_timeouts_are_preserved(paths):
    config = ApplicationConfig(
        environments={"local": EnvironmentConfig(base_url="http://localhost:8000", timeout=2.5)}
    )
    write_config(paths.global_config, config)
    assert "timeout: 2.5\n" in paths.global_config.read_text(encoding="utf-8")
