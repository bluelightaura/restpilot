"""Load an OpenAPI document from a local file or an HTTP(S) URL."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import yaml

from restpilot.exceptions import OpenAPIParseError

#: Timeout used when downloading a remote specification.
DOWNLOAD_TIMEOUT = 30.0


def is_url(source: str) -> bool:
    """Whether ``source`` looks like an HTTP(S) URL."""
    return urlsplit(source).scheme in {"http", "https"}


def parse_document_text(text: str, *, source: str) -> dict[str, Any]:
    """Parse specification text in YAML or JSON form.

    Raises:
        OpenAPIParseError: If the text is not a valid YAML/JSON mapping.
    """
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise OpenAPIParseError(f"{source} is not valid YAML or JSON: {error}.") from error
    if not isinstance(data, dict):
        raise OpenAPIParseError(f"{source} must contain an OpenAPI document (a mapping).")
    return data


def load_from_file(path: Path) -> dict[str, Any]:
    """Read and parse a specification stored on disk."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise OpenAPIParseError(
            f"specification file {path} does not exist.",
            hint="Pass a path to an OpenAPI file, or a http(s) URL.",
        ) from error
    except OSError as error:  # pragma: no cover - depends on the filesystem
        raise OpenAPIParseError(f"cannot read {path}: {error}.") from error
    return parse_document_text(text, source=str(path))


def load_from_url(
    url: str, *, timeout: float = DOWNLOAD_TIMEOUT, verify: bool = True
) -> dict[str, Any]:
    """Download and parse a remote specification.

    Raises:
        OpenAPIParseError: If the document cannot be downloaded or parsed.
    """
    try:
        response = httpx.get(url, timeout=timeout, follow_redirects=True, verify=verify)
    except httpx.TimeoutException as error:
        raise OpenAPIParseError(f"downloading {url} timed out after {timeout}s.") from error
    except httpx.TransportError as error:
        raise OpenAPIParseError(f"cannot download {url}: {error}.") from error
    if response.status_code >= 400:
        raise OpenAPIParseError(
            f"downloading {url} failed with status {response.status_code}.",
            hint="Check that the URL points at a public OpenAPI document.",
        )
    return parse_document_text(response.text, source=url)


def load_spec(
    source: str, *, timeout: float = DOWNLOAD_TIMEOUT, verify: bool = True
) -> dict[str, Any]:
    """Load a specification from a file path or a URL."""
    if is_url(source):
        return load_from_url(source, timeout=timeout, verify=verify)
    return load_from_file(Path(source).expanduser())
