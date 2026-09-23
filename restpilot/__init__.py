"""RestPilot: a CLI tool for exploring, calling and testing REST APIs."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _package_version

try:
    __version__ = _package_version("restpilot")
except PackageNotFoundError:  # pragma: no cover - only when running uninstalled
    # A source tree that was never installed has no version to report. Say so
    # rather than inventing a number that would compete with pyproject.toml as a
    # second source of truth.
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
