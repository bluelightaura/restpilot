"""High level operations on named environments."""

from __future__ import annotations

from pathlib import Path

from restpilot.config import ConfigPaths, load_config
from restpilot.environments.storage import load_config_file, write_config
from restpilot.exceptions import ConfigurationError, EnvironmentNotFoundError
from restpilot.models import ApplicationConfig, EnvironmentConfig
from restpilot.utils.secrets import substitute_env_vars_in_mapping


class EnvironmentManager:
    """Create, select and resolve the environments RestPilot talks to."""

    def __init__(self, paths: ConfigPaths) -> None:
        """Bind the manager to a set of configuration paths."""
        self.paths = paths

    def load(self) -> ApplicationConfig:
        """Return the effective configuration (local overriding global)."""
        return load_config(self.paths)

    def list_environments(self) -> dict[str, EnvironmentConfig]:
        """Return all configured environments by name."""
        return self.load().environments

    def current_name(self) -> str | None:
        """Return the selected environment name, if any."""
        return self.load().current_environment

    def get(self, name: str) -> EnvironmentConfig:
        """Return a single environment definition.

        Raises:
            EnvironmentNotFoundError: If the environment is not configured.
        """
        config = self.load()
        try:
            return config.environments[name]
        except KeyError:
            raise EnvironmentNotFoundError(name, list(config.environments)) from None

    def resolve(self, name: str | None = None) -> tuple[str, EnvironmentConfig]:
        """Return the environment to use, with ``${VAR}`` headers expanded.

        Args:
            name: Explicit environment name. Defaults to the selected one.

        Returns:
            A ``(name, environment)`` pair.

        Raises:
            ConfigurationError: If no environment is selected.
            EnvironmentNotFoundError: If the requested environment is missing.
        """
        config = self.load()
        selected = name or config.current_environment
        if not selected:
            raise ConfigurationError(
                "no environment is selected.",
                hint=(
                    "Create one with 'restpilot env create local --base-url http://localhost:8000' "
                    "and select it with 'restpilot env use local'."
                ),
            )
        try:
            environment = config.environments[selected]
        except KeyError:
            raise EnvironmentNotFoundError(selected, list(config.environments)) from None
        resolved = environment.model_copy(
            update={"headers": substitute_env_vars_in_mapping(environment.headers)}
        )
        return selected, resolved

    def create(
        self,
        name: str,
        *,
        base_url: str,
        timeout: float = 10.0,
        verify_ssl: bool = True,
        headers: dict[str, str] | None = None,
        force: bool = False,
        target: Path | None = None,
    ) -> Path:
        """Add or replace an environment definition.

        Args:
            name: Environment name.
            base_url: Root URL of the API.
            timeout: Request timeout in seconds.
            verify_ssl: Whether TLS certificates are verified.
            headers: Default headers sent with every request.
            force: Allow overwriting an existing environment.
            target: Configuration file to write. Defaults to the active one.

        Returns:
            The path of the configuration file that was written.

        Raises:
            ConfigurationError: If the environment exists and ``force`` is false,
                or if the values are invalid.
        """
        path = target or self.paths.write_target
        config = load_config_file(path)
        if name in config.environments and not force:
            raise ConfigurationError(
                f"environment {name!r} already exists in {path}.",
                hint="Pass --force to overwrite it.",
            )
        try:
            environment = EnvironmentConfig(
                base_url=base_url,
                timeout=timeout,
                verify_ssl=verify_ssl,
                headers=dict(headers or {}),
            )
        except Exception as error:
            raise ConfigurationError(f"invalid environment {name!r}: {error}.") from error
        config.environments[name] = environment
        if config.current_environment is None:
            config.current_environment = name
        return write_config(path, config)

    def use(self, name: str) -> Path:
        """Select ``name`` as the current environment.

        Raises:
            EnvironmentNotFoundError: If the environment is not configured.
        """
        available = self.load().environments
        if name not in available:
            raise EnvironmentNotFoundError(name, list(available))
        path = self.paths.write_target
        config = load_config_file(path)
        if name not in config.environments:
            config.environments[name] = available[name]
        config.current_environment = name
        return write_config(path, config)

    def delete(self, name: str) -> Path:
        """Remove an environment definition from the active configuration file.

        Raises:
            EnvironmentNotFoundError: If the environment is not defined in that file.
        """
        path = self.paths.write_target
        config = load_config_file(path)
        if name not in config.environments:
            raise EnvironmentNotFoundError(name, list(config.environments))
        del config.environments[name]
        if config.current_environment == name:
            config.current_environment = next(iter(config.environments), None)
        return write_config(path, config)
