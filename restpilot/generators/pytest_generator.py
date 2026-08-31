"""Render pytest modules for imported OpenAPI endpoints."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from restpilot.exceptions import TestGenerationError
from restpilot.models import GeneratedTest, HttpMethod, OpenAPIEndpoint, ResponseKind
from restpilot.utils.files import ensure_directory, resolve_output_path, write_text

TEMPLATES_DIR = Path(__file__).parent / "templates"
TEST_TEMPLATE = "api_test.py.j2"
CONFTEST_TEMPLATE = "conftest.py.j2"

#: Placeholder values substituted into path parameters.
_ID_SAMPLE = "1"
_STRING_SAMPLE = "example"

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NON_IDENTIFIER = re.compile(r"[^0-9a-zA-Z]+")


def _jinja_environment() -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        # The templates render Python source, never HTML: escaping would corrupt it.
        autoescape=False,  # noqa: S701
    )


def snake_case(value: str) -> str:
    """Convert an arbitrary identifier to ``snake_case``."""
    spaced = _CAMEL_BOUNDARY.sub("_", value)
    cleaned = _NON_IDENTIFIER.sub("_", spaced).strip("_").lower()
    return re.sub(r"_{2,}", "_", cleaned)


def test_name_for(endpoint: OpenAPIEndpoint) -> str:
    """Build a readable pytest function name for an endpoint."""
    if endpoint.operation_id:
        base = snake_case(endpoint.operation_id)
    else:
        segments: list[str] = []
        for segment in endpoint.path.strip("/").split("/"):
            if not segment:
                continue
            if segment.startswith("{") and segment.endswith("}"):
                segments.append(f"by_{snake_case(segment[1:-1])}")
            else:
                segments.append(snake_case(segment))
        method = endpoint.method.value.lower()
        base = "_".join([method, *segments]) if segments else f"{method}_root"
    if base[0].isdigit():
        base = f"endpoint_{base}"
    return f"test_{base}"


def file_name_for(test_name: str) -> str:
    """Return the module file name for a generated test function."""
    return f"{test_name}.py"


def sample_path(path: str) -> str:
    """Replace ``{param}`` placeholders with stable sample values."""

    def replace(match: re.Match[str]) -> str:
        name = match.group(1).lower()
        return _ID_SAMPLE if name == "id" or name.endswith(("id", "_id")) else _STRING_SAMPLE

    return re.sub(r"\{([^{}]+)\}", replace, path)


def python_literal(value: Any, level: int = 0) -> str:
    """Render a JSON-like value as formatted Python source.

    Double quotes and trailing commas are used so that the generated file is
    already formatted the way Ruff would format it.
    """
    pad = "    " * (level + 1)
    closing = "    " * level
    if isinstance(value, dict):
        if not value:
            return "{}"
        lines = [
            f"{pad}{json.dumps(str(key), ensure_ascii=False)}: {python_literal(item, level + 1)},"
            for key, item in value.items()
        ]
        return "{\n" + "\n".join(lines) + f"\n{closing}}}"
    if isinstance(value, list):
        if not value:
            return "[]"
        lines = [f"{pad}{python_literal(item, level + 1)}," for item in value]
        return "[\n" + "\n".join(lines) + f"\n{closing}]"
    if value is None or isinstance(value, bool):
        return repr(value)
    if isinstance(value, (int, float)):
        return repr(value)
    return json.dumps(str(value), ensure_ascii=False)


def docstring_for(endpoint: OpenAPIEndpoint) -> str:
    """Return the one-line docstring used in the generated test."""
    summary = endpoint.summary.strip().rstrip(".")
    if summary:
        return f"{summary}."
    return f"{endpoint.method.value} {endpoint.path}."


def render_test(
    endpoint: OpenAPIEndpoint, *, base_url: str = "", smoke: bool = False
) -> GeneratedTest:
    """Render the pytest module for a single endpoint.

    Args:
        endpoint: The operation to cover.
        base_url: Recorded in the module docstring for context.
        smoke: Also tag the test with ``@pytest.mark.smoke``.

    Returns:
        The rendered module, not yet written to disk.
    """
    test_name = test_name_for(endpoint)
    has_body = endpoint.request_example is not None and endpoint.method not in {
        HttpMethod.GET,
        HttpMethod.HEAD,
        HttpMethod.OPTIONS,
    }
    body_assertion = {
        ResponseKind.OBJECT: "dict",
        ResponseKind.ARRAY: "list",
        ResponseKind.UNKNOWN: "(dict, list)",
    }.get(endpoint.response_kind)
    if endpoint.method is HttpMethod.HEAD:
        body_assertion = None
    template = _jinja_environment().get_template(TEST_TEMPLATE)
    content = template.render(
        test_name=test_name,
        endpoint=endpoint,
        method=endpoint.method.value.lower(),
        request_path=sample_path(endpoint.path),
        summary=endpoint.summary,
        expected_status=endpoint.success_status,
        payload=python_literal(endpoint.request_example, level=1) if has_body else None,
        docstring=docstring_for(endpoint),
        body_assertion=body_assertion,
        base_url=base_url,
        smoke=smoke,
    )
    return GeneratedTest(
        test_name=test_name,
        file_name=file_name_for(test_name),
        content=content,
        endpoint=endpoint,
    )


def render_conftest(base_url: str) -> str:
    """Render the ``conftest.py`` that provides the ``api_client`` fixture."""
    template = _jinja_environment().get_template(CONFTEST_TEMPLATE)
    return template.render(base_url=base_url or "http://localhost:8000")


def write_test(generated: GeneratedTest, output_dir: Path, *, force: bool = False) -> Path:
    """Write a rendered test module into ``output_dir``.

    Args:
        generated: The rendered module.
        output_dir: Target directory, created when missing.
        force: Overwrite an existing file.

    Returns:
        The written path.

    Raises:
        TestGenerationError: If the file exists and ``force`` is false.
    """
    ensure_directory(output_dir)
    target = resolve_output_path(output_dir, generated.file_name)
    if target.exists() and not force:
        raise TestGenerationError(
            f"{target} already exists.",
            hint="Pass --force to overwrite the generated test.",
        )
    return write_text(target, generated.content)


def ensure_conftest(output_dir: Path, base_url: str, *, force: bool = False) -> Path:
    """Create ``conftest.py`` in ``output_dir`` unless it already exists."""
    ensure_directory(output_dir)
    target = output_dir / "conftest.py"
    if target.exists() and not force:
        return target
    return write_text(target, render_conftest(base_url))
