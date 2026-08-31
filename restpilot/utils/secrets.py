"""Environment variable expansion and masking of sensitive values."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping

from restpilot.exceptions import ConfigurationError

#: Headers whose values must never be printed in full.
SENSITIVE_HEADERS: frozenset[str] = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "api-key",
        "x-auth-token",
    }
)

#: Authentication schemes kept visible in front of a masked credential.
_AUTH_SCHEMES: tuple[str, ...] = ("bearer", "basic", "digest", "token")

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

_VISIBLE_PREFIX = 5


def substitute_env_vars(value: str, *, environ: Mapping[str, str] | None = None) -> str:
    """Replace every ``${VAR}`` placeholder with its environment value.

    Args:
        value: The raw string, possibly containing placeholders.
        environ: Environment mapping to read from. Defaults to ``os.environ``.

    Returns:
        The expanded string.

    Raises:
        ConfigurationError: If a referenced variable is not set.
    """
    source = os.environ if environ is None else environ
    missing: list[str] = []

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in source:
            missing.append(name)
            return match.group(0)
        return source[name]

    expanded = _ENV_PATTERN.sub(replace, value)
    if missing:
        names = ", ".join(sorted(set(missing)))
        raise ConfigurationError(
            f"environment variable {names} is referenced by the configuration but not set.",
            hint=f"Export it before running the command, for example: export {missing[0]}=...",
        )
    return expanded


def substitute_env_vars_in_mapping(
    values: Mapping[str, str], *, environ: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Expand ``${VAR}`` placeholders in every value of a mapping."""
    return {key: substitute_env_vars(value, environ=environ) for key, value in values.items()}


def is_sensitive_header(name: str) -> bool:
    """Whether a header name carries credentials."""
    return name.strip().lower() in SENSITIVE_HEADERS


def mask_secret(value: str) -> str:
    """Mask a credential, keeping only a short recognizable prefix."""
    if not value:
        return value
    parts = value.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() in _AUTH_SCHEMES and parts[1]:
        return f"{parts[0]} {_mask_token(parts[1])}"
    return _mask_token(value)


def _mask_token(token: str) -> str:
    if len(token) <= _VISIBLE_PREFIX:
        return "***"
    return f"{token[:_VISIBLE_PREFIX]}..."


def mask_header(name: str, value: str) -> str:
    """Return the header value, masked when the header is sensitive."""
    return mask_secret(value) if is_sensitive_header(name) else value


def mask_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Return a copy of ``headers`` with every sensitive value masked."""
    return {name: mask_header(name, value) for name, value in headers.items()}
