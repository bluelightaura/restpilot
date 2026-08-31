"""Reading and writing RestPilot YAML configuration files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from restpilot.exceptions import ConfigurationError
from restpilot.models import ApplicationConfig
from restpilot.utils.files import read_text, write_text


def read_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML mapping from ``path``.

    Args:
        path: File to read.

    Returns:
        The parsed mapping, or an empty dict when the file does not exist or is empty.

    Raises:
        ConfigurationError: If the file is not valid YAML or is not a mapping.
    """
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(read_text(path))
    except yaml.YAMLError as error:
        raise ConfigurationError(f"{path} is not valid YAML: {error}.") from error
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigurationError(f"{path} must contain a YAML mapping at the top level.")
    return data


def parse_config(data: dict[str, Any], *, source: Path) -> ApplicationConfig:
    """Validate a raw mapping into an :class:`ApplicationConfig`."""
    try:
        return ApplicationConfig.model_validate(data)
    except Exception as error:  # pydantic.ValidationError and friends
        raise ConfigurationError(f"invalid configuration in {source}: {error}.") from error


def load_config_file(path: Path) -> ApplicationConfig:
    """Read and validate a single configuration file."""
    return parse_config(read_yaml(path), source=path)


def config_to_dict(config: ApplicationConfig) -> dict[str, Any]:
    """Serialize a configuration to a compact, human-friendly mapping."""
    payload: dict[str, Any] = {}
    if config.current_environment:
        payload["current_environment"] = config.current_environment
    environments: dict[str, Any] = {}
    for name, environment in config.environments.items():
        timeout = environment.timeout
        entry: dict[str, Any] = {
            "base_url": environment.base_url,
            # Keep whole seconds readable as "10" instead of "10.0".
            "timeout": int(timeout) if timeout.is_integer() else timeout,
            "verify_ssl": environment.verify_ssl,
        }
        if environment.headers:
            entry["headers"] = dict(environment.headers)
        environments[name] = entry
    payload["environments"] = environments
    return payload


def write_config(path: Path, config: ApplicationConfig) -> Path:
    """Write a configuration file with owner-only permissions."""
    content = yaml.safe_dump(config_to_dict(config), sort_keys=False, allow_unicode=True)
    header = "# Managed by RestPilot. Use ${VAR} placeholders instead of literal secrets.\n"
    return write_text(path, header + content, private=True)
