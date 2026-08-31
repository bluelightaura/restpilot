"""Configuration discovery and merging.

RestPilot reads two files:

* a global one, ``~/.config/restpilot/config.yaml``;
* an optional project-local ``.restpilot.yaml`` found in the current directory
  or any parent directory.

The local file always takes precedence over the global one.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from restpilot.environments.storage import load_config_file
from restpilot.models import ApplicationConfig

#: Overrides the global configuration directory (used by tests and CI).
CONFIG_HOME_ENV = "RESTPILOT_CONFIG_HOME"
LOCAL_CONFIG_NAME = ".restpilot.yaml"
GLOBAL_CONFIG_NAME = "config.yaml"
LOCAL_STATE_DIR = ".restpilot"
SPEC_FILE_NAME = "api.json"
DEFAULT_GENERATED_TESTS_DIR = "generated_tests"


def global_config_dir() -> Path:
    """Return the directory holding the global configuration."""
    override = os.environ.get(CONFIG_HOME_ENV)
    if override:
        return Path(override).expanduser()
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg_config_home).expanduser() if xdg_config_home else Path.home() / ".config"
    return base / "restpilot"


def find_local_config(start: Path | None = None) -> Path | None:
    """Search ``start`` and its parents for a ``.restpilot.yaml`` file."""
    current = (start or Path.cwd()).resolve()
    for directory in [current, *current.parents]:
        candidate = directory / LOCAL_CONFIG_NAME
        if candidate.is_file():
            return candidate
    return None


@dataclass(frozen=True)
class ConfigPaths:
    """Where RestPilot reads configuration and stores imported specifications."""

    global_config: Path
    local_config: Path | None

    @classmethod
    def discover(cls, start: Path | None = None) -> ConfigPaths:
        """Locate the global and project-local configuration files."""
        return cls(
            global_config=global_config_dir() / GLOBAL_CONFIG_NAME,
            local_config=find_local_config(start),
        )

    @property
    def write_target(self) -> Path:
        """The file that ``env`` commands modify by default."""
        return self.local_config or self.global_config

    @property
    def spec_path(self) -> Path:
        """Where the normalized OpenAPI document is stored."""
        if self.local_config is not None:
            return self.local_config.parent / LOCAL_STATE_DIR / SPEC_FILE_NAME
        return global_config_dir() / SPEC_FILE_NAME

    @property
    def generated_tests_dir(self) -> Path:
        """Default output directory for generated pytest modules."""
        root = self.local_config.parent if self.local_config is not None else Path.cwd()
        return root / DEFAULT_GENERATED_TESTS_DIR


def merge_configs(base: ApplicationConfig, override: ApplicationConfig) -> ApplicationConfig:
    """Merge two configurations, letting ``override`` win per environment name."""
    environments = dict(base.environments)
    environments.update(override.environments)
    return ApplicationConfig(
        current_environment=override.current_environment or base.current_environment,
        environments=environments,
    )


def load_config(paths: ConfigPaths) -> ApplicationConfig:
    """Load the effective configuration for ``paths``."""
    config = load_config_file(paths.global_config)
    if paths.local_config is not None:
        config = merge_configs(config, load_config_file(paths.local_config))
    return config
