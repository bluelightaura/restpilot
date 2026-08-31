"""Turn CLI arguments and an environment into a :class:`RequestDefinition`."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import urlsplit

from restpilot.exceptions import ConfigurationError
from restpilot.models import EnvironmentConfig, HttpMethod, RequestDefinition

_SEPARATORS = ("=", ":")


def build_url(base_url: str, path: str) -> str:
    """Join ``base_url`` and ``path`` without losing a base path prefix.

    Absolute URLs are returned unchanged, which makes ``restpilot call GET
    https://example.com/health`` work without a configured environment.
    """
    target = path.strip()
    if not target:
        raise ConfigurationError("request path must not be empty.")
    if urlsplit(target).scheme in {"http", "https"}:
        return target
    return f"{base_url.rstrip('/')}/{target.lstrip('/')}"


def parse_key_value(raw: str, *, kind: str) -> tuple[str, str]:
    """Parse a ``key=value`` (or ``key: value``) CLI argument.

    Args:
        raw: The raw argument.
        kind: Human readable name used in error messages.

    Returns:
        The ``(key, value)`` pair, with surrounding whitespace stripped.

    Raises:
        ConfigurationError: If no separator is present or the key is empty.
    """
    positions = [raw.find(separator) for separator in _SEPARATORS]
    candidates = [index for index in positions if index > 0]
    if not candidates:
        raise ConfigurationError(
            f"invalid {kind} {raw!r}.",
            hint=f"Use the form 'name=value', for example: --{kind} limit=10.",
        )
    index = min(candidates)
    key = raw[:index].strip()
    value = raw[index + 1 :].strip()
    if not key:
        raise ConfigurationError(f"invalid {kind} {raw!r}: the name is empty.")
    return key, value


def parse_headers(values: Iterable[str]) -> dict[str, str]:
    """Parse repeated ``--header`` options into a mapping."""
    return dict(parse_key_value(value, kind="header") for value in values)


def parse_query(values: Iterable[str]) -> list[tuple[str, str]]:
    """Parse repeated ``--query`` options, preserving duplicate keys."""
    return [parse_key_value(value, kind="query") for value in values]


def parse_json_body(raw: str) -> Any:
    """Parse a JSON payload provided on the command line.

    Raises:
        ConfigurationError: If the payload is not valid JSON.
    """
    try:
        return json.loads(raw)
    except json.JSONDecodeError as error:
        raise ConfigurationError(
            f"--json payload is not valid JSON: {error.msg} (line {error.lineno}).",
            hint='Wrap the payload in single quotes: --json \'{"name": "Alice"}\'.',
        ) from error


def merge_headers(base: Mapping[str, str], override: Mapping[str, str]) -> dict[str, str]:
    """Merge headers case-insensitively, letting ``override`` win."""
    merged = dict(base)
    lowered = {name.lower(): name for name in merged}
    for name, value in override.items():
        existing = lowered.get(name.lower())
        if existing is not None:
            del merged[existing]
        merged[name] = value
        lowered[name.lower()] = name
    return merged


def build_request(
    environment: EnvironmentConfig,
    method: HttpMethod,
    path: str,
    *,
    headers: Mapping[str, str] | None = None,
    query: Iterable[tuple[str, str]] | None = None,
    json_body: Any = None,
    content: str | None = None,
    timeout: float | None = None,
    verify_ssl: bool | None = None,
) -> RequestDefinition:
    """Combine an environment and CLI arguments into a request definition.

    Raises:
        ConfigurationError: If both a JSON body and raw data are provided.
    """
    if json_body is not None and content is not None:
        raise ConfigurationError(
            "--json and --data cannot be used together.",
            hint="Pick one payload option.",
        )
    return RequestDefinition(
        method=method,
        url=build_url(environment.base_url, path),
        headers=merge_headers(environment.headers, headers or {}),
        query=list(query or []),
        json_body=json_body,
        content=content,
        timeout=environment.timeout if timeout is None else timeout,
        verify_ssl=environment.verify_ssl if verify_ssl is None else verify_ssl,
    )
