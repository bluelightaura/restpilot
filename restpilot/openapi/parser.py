"""Normalize an OpenAPI 3.x document into RestPilot's own models."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from restpilot.exceptions import OpenAPIParseError
from restpilot.models import HttpMethod, OpenAPIDocument, OpenAPIEndpoint, ResponseKind
from restpilot.utils.files import read_text, write_text

#: Keys inside a path item that are not operations.
_NON_OPERATION_KEYS = frozenset({"$ref", "summary", "description", "servers", "parameters"})

#: How deep example generation walks into a JSON schema.
_MAX_EXAMPLE_DEPTH = 4

_TYPE_EXAMPLES: dict[str, Any] = {
    "string": "string",
    "integer": 1,
    "number": 1.0,
    "boolean": True,
    "array": [],
    "object": {},
}


def resolve_ref(document: dict[str, Any], node: Any, *, seen: frozenset[str] = frozenset()) -> Any:
    """Follow a local ``$ref`` inside ``document``.

    Unknown or remote references are returned as-is instead of raising, so that
    partially resolvable documents still import.
    """
    if not isinstance(node, dict):
        return node
    ref = node.get("$ref")
    if not isinstance(ref, str) or not ref.startswith("#/") or ref in seen:
        return node
    target: Any = document
    for part in ref[2:].split("/"):
        key = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(target, dict) or key not in target:
            return node
        target = target[key]
    return resolve_ref(document, target, seen=seen | {ref})


def example_from_schema(document: dict[str, Any], schema: Any, *, depth: int = 0) -> Any:
    """Build a small example payload from a JSON schema."""
    schema = resolve_ref(document, schema)
    if not isinstance(schema, dict) or depth >= _MAX_EXAMPLE_DEPTH:
        return None
    if "example" in schema:
        return schema["example"]
    if isinstance(schema.get("default"), (str, int, float, bool)):
        return schema["default"]
    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and enum_values:
        return enum_values[0]
    schema_type = schema.get("type")
    if schema_type == "object" or "properties" in schema:
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            return {}
        return {
            name: example_from_schema(document, subschema, depth=depth + 1)
            for name, subschema in properties.items()
        }
    if schema_type == "array":
        item = example_from_schema(document, schema.get("items"), depth=depth + 1)
        return [item] if item is not None else []
    if isinstance(schema_type, str):
        return _TYPE_EXAMPLES.get(schema_type)
    return None


def _request_example(document: dict[str, Any], operation: dict[str, Any]) -> Any:
    body = resolve_ref(document, operation.get("requestBody"))
    if not isinstance(body, dict):
        return None
    content = body.get("content")
    if not isinstance(content, dict):
        return None
    for media_type, media in content.items():
        if "json" not in media_type.lower() or not isinstance(media, dict):
            continue
        if "example" in media:
            return media["example"]
        examples = media.get("examples")
        if isinstance(examples, dict):
            for example in examples.values():
                resolved = resolve_ref(document, example)
                if isinstance(resolved, dict) and "value" in resolved:
                    return resolved["value"]
        return example_from_schema(document, media.get("schema"))
    return None


def _success_status(operation: dict[str, Any]) -> int:
    responses = operation.get("responses")
    if not isinstance(responses, dict):
        return 200
    codes = []
    for raw_code in responses:
        try:
            code = int(raw_code)
        except (TypeError, ValueError):
            continue
        if 200 <= code < 300:
            codes.append(code)
    return min(codes) if codes else 200


def _response_kind(
    document: dict[str, Any], operation: dict[str, Any], status: int
) -> ResponseKind:
    responses = operation.get("responses")
    if not isinstance(responses, dict):
        return ResponseKind.UNKNOWN
    entry = resolve_ref(document, responses.get(str(status), responses.get(status)))
    if not isinstance(entry, dict):
        return ResponseKind.UNKNOWN
    content = entry.get("content")
    if not isinstance(content, dict) or not content:
        return ResponseKind.NONE
    for media_type, media in content.items():
        if "json" not in media_type.lower() or not isinstance(media, dict):
            continue
        schema = resolve_ref(document, media.get("schema"))
        if not isinstance(schema, dict):
            return ResponseKind.UNKNOWN
        if schema.get("type") == "array":
            return ResponseKind.ARRAY
        if schema.get("type") == "object" or "properties" in schema:
            return ResponseKind.OBJECT
        return ResponseKind.UNKNOWN
    return ResponseKind.UNKNOWN


def _parse_operation(
    document: dict[str, Any], method: HttpMethod, path: str, operation: dict[str, Any]
) -> OpenAPIEndpoint:
    summary = operation.get("summary") or operation.get("description") or ""
    tags = [str(tag) for tag in operation.get("tags", []) if isinstance(tag, (str, int))]
    operation_id = operation.get("operationId")
    status = _success_status(operation)
    return OpenAPIEndpoint(
        method=method,
        path=path,
        summary=str(summary).strip().splitlines()[0] if summary else "",
        operation_id=str(operation_id) if operation_id else None,
        success_status=status,
        response_kind=_response_kind(document, operation, status),
        request_example=_request_example(document, operation),
        tags=tags,
    )


def parse_spec(raw: dict[str, Any], *, source: str = "") -> OpenAPIDocument:
    """Convert a raw OpenAPI mapping into an :class:`OpenAPIDocument`.

    Unknown or optional fields are ignored rather than rejected.

    Raises:
        OpenAPIParseError: If the document is not OpenAPI 3.x or has no paths.
    """
    version = raw.get("openapi")
    if not isinstance(version, str) or not version.strip():
        raise OpenAPIParseError(
            "the document has no 'openapi' field.",
            hint="RestPilot supports OpenAPI 3.x documents (Swagger 2.0 is not supported).",
        )
    if not version.startswith("3."):
        raise OpenAPIParseError(
            f"unsupported OpenAPI version {version!r}.",
            hint="RestPilot supports OpenAPI 3.x documents.",
        )
    raw_info = raw.get("info")
    info: dict[str, Any] = raw_info if isinstance(raw_info, dict) else {}
    paths = raw.get("paths")
    if not isinstance(paths, dict) or not paths:
        raise OpenAPIParseError("the document does not declare any paths.")

    endpoints: list[OpenAPIEndpoint] = []
    for path, path_item in paths.items():
        resolved_item = resolve_ref(raw, path_item)
        if not isinstance(resolved_item, dict):
            continue
        for key, operation in resolved_item.items():
            if key in _NON_OPERATION_KEYS or not isinstance(operation, dict):
                continue
            try:
                method = HttpMethod.parse(str(key))
            except ValueError:
                continue
            endpoints.append(_parse_operation(raw, method, str(path), operation))

    if not endpoints:
        raise OpenAPIParseError("the document does not declare any operations.")

    endpoints.sort(key=lambda endpoint: (endpoint.path, endpoint.method.value))
    return OpenAPIDocument(
        title=str(info.get("title") or "Unnamed API"),
        version=str(info.get("version") or "0.0.0"),
        source=source,
        endpoints=endpoints,
    )


def filter_endpoints(
    endpoints: list[OpenAPIEndpoint],
    *,
    method: HttpMethod | None = None,
    search: str | None = None,
) -> list[OpenAPIEndpoint]:
    """Filter endpoints by HTTP method and by a case-insensitive substring."""
    selected = list(endpoints)
    if method is not None:
        selected = [endpoint for endpoint in selected if endpoint.method is method]
    if search:
        needle = search.lower()
        selected = [
            endpoint
            for endpoint in selected
            if needle in endpoint.path.lower()
            or needle in endpoint.summary.lower()
            or needle in (endpoint.operation_id or "").lower()
            or any(needle in tag.lower() for tag in endpoint.tags)
        ]
    return selected


def find_endpoint(
    document: OpenAPIDocument, method: HttpMethod, path: str
) -> OpenAPIEndpoint | None:
    """Look up a single operation by method and path."""
    normalized = path if path.startswith("/") else f"/{path}"
    for endpoint in document.endpoints:
        if endpoint.method is method and endpoint.path == normalized:
            return endpoint
    return None


def save_document(path: Path, document: OpenAPIDocument) -> Path:
    """Persist the normalized document as JSON."""
    return write_text(path, document.model_dump_json(indent=2) + "\n")


def load_document(path: Path) -> OpenAPIDocument:
    """Load a previously imported document.

    Raises:
        OpenAPIParseError: If nothing was imported yet or the cache is corrupt.
    """
    if not path.exists():
        raise OpenAPIParseError(
            "no OpenAPI specification has been imported yet.",
            hint="Run 'restpilot import-api openapi.yaml' first.",
        )
    try:
        return OpenAPIDocument.model_validate(json.loads(read_text(path)))
    except (json.JSONDecodeError, ValueError) as error:
        raise OpenAPIParseError(
            f"the imported specification at {path} is corrupt: {error}.",
            hint="Import the specification again.",
        ) from error
