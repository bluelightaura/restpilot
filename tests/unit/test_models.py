"""Model validation and derived properties."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from restpilot.models import (
    EnvironmentConfig,
    HttpMethod,
    OpenAPIEndpoint,
    RequestDefinition,
    ResponseResult,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("raw", "expected"), [("get", HttpMethod.GET), (" PoSt ", HttpMethod.POST)]
)
def test_http_method_parse_is_case_insensitive(raw, expected):
    assert HttpMethod.parse(raw) is expected


def test_http_method_parse_rejects_unknown_methods():
    with pytest.raises(ValueError, match="unsupported HTTP method"):
        HttpMethod.parse("TRACE")


def test_environment_requires_a_scheme():
    with pytest.raises(ValidationError):
        EnvironmentConfig(base_url="localhost:8000")


def test_environment_rejects_an_empty_base_url():
    with pytest.raises(ValidationError):
        EnvironmentConfig(base_url="   ")


def test_environment_rejects_a_negative_timeout():
    with pytest.raises(ValidationError):
        EnvironmentConfig(base_url="http://localhost:8000", timeout=0)


def test_request_definition_knows_safe_methods():
    safe = RequestDefinition(method=HttpMethod.HEAD, url="http://localhost/health")
    unsafe = RequestDefinition(method=HttpMethod.DELETE, url="http://localhost/users/1")
    assert safe.is_safe and not unsafe.is_safe


def test_response_result_parses_a_json_body():
    result = ResponseResult(
        method=HttpMethod.GET,
        url="http://localhost/users/1",
        status_code=200,
        headers={"Content-Type": "application/json"},
        body='{"id": 1}',
    )
    assert result.is_json
    assert result.content_type == "application/json"
    assert result.json_body() == {"id": 1}


def test_response_result_returns_none_for_invalid_json():
    result = ResponseResult(
        method=HttpMethod.GET,
        url="http://localhost/health",
        status_code=200,
        headers={"content-type": "text/plain"},
        body="pong",
    )
    assert not result.is_json
    assert result.json_body() is None


def test_response_result_handles_an_empty_body():
    result = ResponseResult(
        method=HttpMethod.DELETE, url="http://localhost/users/1", status_code=204
    )
    assert result.json_body() is None
    assert result.content_type is None


def test_endpoint_key_combines_method_and_path():
    endpoint = OpenAPIEndpoint(method=HttpMethod.GET, path="/users")
    assert endpoint.key == "GET /users"
