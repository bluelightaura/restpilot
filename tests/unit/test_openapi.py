"""Loading, parsing and filtering OpenAPI documents."""

from __future__ import annotations

import json

import pytest

from restpilot.exceptions import OpenAPIParseError
from restpilot.models import HttpMethod, ResponseKind
from restpilot.openapi.loader import load_spec, parse_document_text
from restpilot.openapi.parser import (
    example_from_schema,
    filter_endpoints,
    find_endpoint,
    load_document,
    parse_spec,
    resolve_ref,
    save_document,
)

pytestmark = pytest.mark.unit

MINIMAL_SPEC = {
    "openapi": "3.0.3",
    "info": {"title": "Tiny API", "version": "2.1.0"},
    "paths": {
        "/ping": {
            "summary": "ignored",
            "parameters": [],
            "get": {"summary": "Ping", "responses": {"200": {"description": "pong"}}},
            "trace": {"summary": "not supported"},
        }
    },
}


def test_parse_spec_extracts_metadata_and_endpoints(document):
    assert document.title == "Demo Users API"
    assert document.version == "1.0.0"
    assert {endpoint.key for endpoint in document.endpoints} == {
        "GET /health",
        "GET /api/v1/users",
        "POST /api/v1/users",
        "GET /api/v1/users/{user_id}",
        "DELETE /api/v1/users/{user_id}",
    }


def test_parse_spec_resolves_request_body_examples(document):
    endpoint = find_endpoint(document, HttpMethod.POST, "/api/v1/users")
    assert endpoint is not None
    assert endpoint.request_example == {"name": "Alice", "email": "alice@example.com"}
    assert endpoint.success_status == 201
    assert endpoint.response_kind is ResponseKind.OBJECT


def test_parse_spec_detects_array_and_empty_responses(document):
    listing = find_endpoint(document, HttpMethod.GET, "/api/v1/users")
    deletion = find_endpoint(document, HttpMethod.DELETE, "/api/v1/users/{user_id}")
    assert listing is not None and listing.response_kind is ResponseKind.ARRAY
    assert deletion is not None
    assert deletion.success_status == 204
    assert deletion.response_kind is ResponseKind.NONE


def test_parse_spec_keeps_tags_and_operation_ids(document):
    endpoint = find_endpoint(document, HttpMethod.GET, "/health")
    assert endpoint is not None
    assert endpoint.operation_id == "healthCheck"
    assert endpoint.tags == ["system"]


def test_parse_spec_ignores_unknown_and_non_operation_keys():
    document = parse_spec(MINIMAL_SPEC)
    assert len(document.endpoints) == 1
    assert document.endpoints[0].method is HttpMethod.GET


def test_parse_spec_defaults_missing_info_fields():
    document = parse_spec({**MINIMAL_SPEC, "info": {}})
    assert document.title == "Unnamed API"
    assert document.version == "0.0.0"


def test_parse_spec_requires_the_openapi_field():
    with pytest.raises(OpenAPIParseError) as error:
        parse_spec({"info": {}, "paths": {}})
    assert "no 'openapi' field" in error.value.message


def test_parse_spec_rejects_swagger_two():
    with pytest.raises(OpenAPIParseError) as error:
        parse_spec({"openapi": "2.0", "paths": {}})
    assert "unsupported OpenAPI version" in error.value.message


def test_parse_spec_requires_paths():
    with pytest.raises(OpenAPIParseError) as error:
        parse_spec({"openapi": "3.0.0", "paths": {}})
    assert "any paths" in error.value.message


def test_parse_spec_requires_at_least_one_operation():
    with pytest.raises(OpenAPIParseError) as error:
        parse_spec({"openapi": "3.0.0", "paths": {"/ping": {"summary": "nothing"}}})
    assert "any operations" in error.value.message


def test_parse_spec_picks_the_lowest_success_status():
    spec = {
        "openapi": "3.0.0",
        "paths": {
            "/things": {
                "post": {
                    "responses": {"202": {"description": "queued"}, "201": {"description": "ok"}}
                }
            }
        },
    }
    assert parse_spec(spec).endpoints[0].success_status == 201


def test_resolve_ref_follows_local_references():
    spec = {"components": {"schemas": {"User": {"type": "object"}}}}
    assert resolve_ref(spec, {"$ref": "#/components/schemas/User"}) == {"type": "object"}


def test_resolve_ref_returns_unknown_references_unchanged():
    node = {"$ref": "https://example.com/schema.json"}
    assert resolve_ref({}, node) == node
    assert resolve_ref({}, {"$ref": "#/nope/missing"}) == {"$ref": "#/nope/missing"}


def test_example_from_schema_builds_a_shallow_payload():
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "active": {"type": "boolean"},
            "score": {"type": "number"},
            "tags": {"type": "array", "items": {"type": "string"}},
            "role": {"enum": ["admin", "user"]},
        },
    }
    assert example_from_schema({}, schema) == {
        "name": "string",
        "active": True,
        "score": 1.0,
        "tags": ["string"],
        "role": "admin",
    }


def test_example_from_schema_handles_unusable_schemas():
    assert example_from_schema({}, None) is None
    assert example_from_schema({}, {"type": "object"}) == {}


def test_filter_endpoints_by_method(document):
    selected = filter_endpoints(document.endpoints, method=HttpMethod.GET)
    assert {endpoint.method for endpoint in selected} == {HttpMethod.GET}
    assert len(selected) == 3


def test_filter_endpoints_by_search_term(document):
    by_path = filter_endpoints(document.endpoints, search="users")
    by_tag = filter_endpoints(document.endpoints, search="SYSTEM")
    by_summary = filter_endpoints(document.endpoints, search="health probe")
    assert len(by_path) == 4
    assert [endpoint.path for endpoint in by_tag] == ["/health"]
    assert [endpoint.path for endpoint in by_summary] == ["/health"]


def test_filter_endpoints_returns_everything_without_filters(document):
    assert filter_endpoints(document.endpoints) == document.endpoints


def test_find_endpoint_normalizes_a_missing_leading_slash(document):
    assert find_endpoint(document, HttpMethod.GET, "health") is not None
    assert find_endpoint(document, HttpMethod.PUT, "/health") is None


def test_documents_round_trip_through_disk(tmp_path, document):
    target = save_document(tmp_path / "api.json", document)
    assert load_document(target) == document


def test_load_document_requires_an_import(tmp_path):
    with pytest.raises(OpenAPIParseError) as error:
        load_document(tmp_path / "api.json")
    assert "no OpenAPI specification has been imported" in error.value.message


def test_load_document_reports_a_corrupt_cache(tmp_path):
    target = tmp_path / "api.json"
    target.write_text("{not json", encoding="utf-8")
    with pytest.raises(OpenAPIParseError) as error:
        load_document(target)
    assert "corrupt" in error.value.message


def test_load_spec_reads_yaml_and_json(tmp_path, example_spec):
    yaml_spec = load_spec(str(example_spec))
    json_target = tmp_path / "openapi.json"
    json_target.write_text(json.dumps(yaml_spec), encoding="utf-8")
    assert load_spec(str(json_target)) == yaml_spec


def test_load_spec_reports_a_missing_file(tmp_path):
    with pytest.raises(OpenAPIParseError) as error:
        load_spec(str(tmp_path / "missing.yaml"))
    assert "does not exist" in error.value.message


def test_parse_document_text_rejects_a_scalar_document():
    with pytest.raises(OpenAPIParseError):
        parse_document_text("just a string", source="inline")


def test_parse_document_text_rejects_broken_yaml():
    with pytest.raises(OpenAPIParseError) as error:
        parse_document_text("paths: [unclosed", source="inline")
    assert "not valid YAML or JSON" in error.value.message
