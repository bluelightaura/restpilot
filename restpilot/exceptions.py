"""Exception hierarchy used across RestPilot.

Every expected failure is expressed as a :class:`RestPilotError`. The CLI turns
those into short, actionable messages instead of tracebacks.
"""

from __future__ import annotations


class RestPilotError(Exception):
    """Base class for all expected RestPilot failures.

    Args:
        message: Short description of what went wrong.
        hint: Optional follow-up action the user can take.
    """

    def __init__(self, message: str, hint: str | None = None) -> None:
        """Store the message and the optional hint."""
        super().__init__(message)
        self.message = message
        self.hint = hint

    def __str__(self) -> str:
        """Return the short message, without the hint."""
        return self.message


class ConfigurationError(RestPilotError):
    """Raised when configuration files or CLI arguments are invalid."""


class EnvironmentNotFoundError(RestPilotError):
    """Raised when a requested environment is not configured."""

    def __init__(self, name: str, available: list[str] | None = None) -> None:
        """Build the message from the missing name and the known environments."""
        hint = "Use 'restpilot env list' to view configured environments."
        if available:
            hint = f"Available environments: {', '.join(sorted(available))}."
        super().__init__(f"environment {name!r} does not exist.", hint)
        self.name = name


class RequestExecutionError(RestPilotError):
    """Raised when an HTTP request cannot be completed."""


class OpenAPIParseError(RestPilotError):
    """Raised when an OpenAPI document cannot be loaded or parsed."""


class TestGenerationError(RestPilotError):
    """Raised when a pytest file cannot be generated."""
