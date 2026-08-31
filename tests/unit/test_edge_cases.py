"""Defensive paths: malformed documents, odd arguments and error rendering."""

from __future__ import annotations

from typing import Any

import pytest

from restpilot.api.request_builder import parse_key_value
from restpilot.exceptions import (
    ConfigurationError,
    EnvironmentNotFoundError,
    RestPilotError,
)
from restpilot.generators.pytest_generator import render_test
from restpilot.models import HttpMethod, OpenAPIEndpoint, ResponseKind
from restpilot.openapi.parser import example_from_schema, parse_spec, resolve_ref

pytestmark = pytest.mark.unit


def test_errors_render_as_their_message():
    error = RestPilotError("something broke", hint="try again")
    assert str(error) == "something broke"
    assert error.hint == "try again"


def test_environment_not_found_without_alternatives():
    error = EnvironmentNotFoundError("stage")
    assert error.name == "stage"
    assert "env list" in (error.hint or "")


def test_parse_key_value_rejects_a_whitespace_only_name():
    with pytest.raises(ConfigurationError) as error:
        parse_key_value("  =value", kind="header")
    assert "the name is empty" in error.value.message


def test_head_requests_do_not_assert_on_a_body():
    endpoint = OpenAPIEndpoint(
        method=HttpMethod.HEAD, path="/health", response_kind=ResponseKind.OBJECT
    )
    assert "response.json()" not in render_test(endpoint).content


def test_resolve_ref_ignores_non_mapping_nodes():
    assert resolve_ref({}, ["not", "a", "mapping"]) == ["not", "a", "mapping"]
    assert resolve_ref({}, {"$ref": 42}) == {"$ref": 42}


def test_resolve_ref_unescapes_json_pointer_tokens():
    document: dict[str, Any] = {"paths": {"/a~b": {"get": {}}}}
    assert resolve_ref(document, {"$ref": "#/paths/~1a~0b/get"}) == {}


def test_resolve_ref_stops_on_a_cycle():
    document: dict[str, Any] = {
        "components": {"schemas": {"Loop": {"$ref": "#/components/schemas/Loop"}}}
    }
    node = {"$ref": "#/components/schemas/Loop"}
    assert resolve_ref(document, node) == node


def test_example_from_schema_stops_at_the_depth_limit():
    schema: dict[str, Any] = {"type": "object", "properties": {}}
    deepest = schema
    for _ in range(6):
        nested: dict[str, Any] = {"type": "object", "properties": {}}
        deepest["properties"] = {"child": nested}
        deepest = nested
    assert example_from_schema({}, schema) == {"child": {"child": {"child": {"child": None}}}}


def test_example_from_schema_uses_scalar_defaults():
    assert example_from_schema({}, {"type": "string", "default": "ok"}) == "ok"
    assert example_from_schema({}, {"type": "object", "properties": "broken"}) == {}
    assert example_from_schema({}, {"type": "unknown-type"}) is None
    assert example_from_schema({}, {"type": "array"}) == []


def test_parse_spec_tolerates_broken_path_items_and_operations():
    spec: dict[str, Any] = {
        "openapi": "3.0.1",
        "info": {"title": "Odd API", "version": "1"},
        "paths": {
            "/broken": "not a mapping",
            "/ok": {"get": {"responses": "not a mapping"}, "post": "not a mapping"},
        },
    }
    document = parse_spec(spec)
    assert [endpoint.key for endpoint in document.endpoints] == ["GET /ok"]
    assert document.endpoints[0].success_status == 200
    assert document.endpoints[0].response_kind is ResponseKind.UNKNOWN


def test_parse_spec_ignores_unusable_response_declarations():
    spec: dict[str, Any] = {
        "openapi": "3.0.1",
        "paths": {
            "/a": {
                "get": {
                    "responses": {
                        "not-a-status": {"description": "ignored"},
                        "200": "not a mapping",
                    }
                }
            },
            "/b": {"get": {"responses": {"200": {"content": {"text/csv": {}}}}}},
            "/c": {"get": {"responses": {"200": {"content": {"application/json": {}}}}}},
        },
    }
    kinds = {endpoint.path: endpoint.response_kind for endpoint in parse_spec(spec).endpoints}
    assert kinds["/a"] is ResponseKind.UNKNOWN
    assert kinds["/b"] is ResponseKind.UNKNOWN
    assert kinds["/c"] is ResponseKind.UNKNOWN


def test_parse_spec_reads_request_examples_from_every_form():
    spec: dict[str, Any] = {
        "openapi": "3.0.1",
        "paths": {
            "/inline": {
                "post": {
                    "requestBody": {"content": {"application/json": {"example": {"a": 1}}}},
                    "responses": {"200": {}},
                }
            },
            "/named": {
                "post": {
                    "requestBody": {
                        "content": {
                            "application/json": {"examples": {"first": {"value": {"b": 2}}}}
                        }
                    },
                    "responses": {"200": {}},
                }
            },
            "/text-only": {
                "post": {
                    "requestBody": {"content": {"text/plain": {"example": "ignored"}}},
                    "responses": {"200": {}},
                }
            },
            "/no-body": {"post": {"requestBody": "not a mapping", "responses": {"200": {}}}},
        },
    }
    examples = {endpoint.path: endpoint.request_example for endpoint in parse_spec(spec).endpoints}
    assert examples["/inline"] == {"a": 1}
    assert examples["/named"] == {"b": 2}
    assert examples["/text-only"] is None
    assert examples["/no-body"] is None


def test_parse_spec_follows_a_path_item_reference():
    spec: dict[str, Any] = {
        "openapi": "3.0.1",
        "paths": {"/users": {"$ref": "#/components/pathItems/Users"}},
        "components": {"pathItems": {"Users": {"get": {"summary": "List users"}}}},
    }
    document = parse_spec(spec)
    assert document.endpoints[0].summary == "List users"


def test_parse_spec_uses_the_description_when_no_summary_exists():
    spec: dict[str, Any] = {
        "openapi": "3.0.1",
        "paths": {"/x": {"get": {"description": "First line\nsecond line", "tags": ["a", None]}}},
    }
    endpoint = parse_spec(spec).endpoints[0]
    assert endpoint.summary == "First line"
    assert endpoint.tags == ["a"]
