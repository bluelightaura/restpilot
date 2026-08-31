"""URL, header, query and body construction."""

from __future__ import annotations

import pytest

from restpilot.api.request_builder import (
    build_request,
    build_url,
    merge_headers,
    parse_headers,
    parse_json_body,
    parse_key_value,
    parse_query,
)
from restpilot.exceptions import ConfigurationError
from restpilot.models import EnvironmentConfig, HttpMethod

pytestmark = pytest.mark.unit


@pytest.fixture
def environment():
    return EnvironmentConfig(
        base_url="http://localhost:8000",
        timeout=15,
        headers={"Accept": "application/json"},
    )


@pytest.mark.parametrize(
    ("base_url", "path", "expected"),
    [
        ("http://localhost:8000", "/users", "http://localhost:8000/users"),
        ("http://localhost:8000/", "users", "http://localhost:8000/users"),
        ("http://localhost:8000/api", "/v1/users", "http://localhost:8000/api/v1/users"),
        ("https://example.com/api/", "/v1/users/", "https://example.com/api/v1/users/"),
    ],
)
def test_build_url_joins_base_and_path(base_url, path, expected):
    assert build_url(base_url, path) == expected


def test_build_url_passes_absolute_urls_through():
    assert build_url("http://localhost:8000", "https://example.com/health") == (
        "https://example.com/health"
    )


def test_build_url_rejects_an_empty_path():
    with pytest.raises(ConfigurationError):
        build_url("http://localhost:8000", "  ")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("limit=10", ("limit", "10")),
        ("Content-Type: application/json", ("Content-Type", "application/json")),
        ("X-Trace=a:b:c", ("X-Trace", "a:b:c")),
        ("q=", ("q", "")),
    ],
)
def test_parse_key_value_supports_both_separators(raw, expected):
    assert parse_key_value(raw, kind="header") == expected


@pytest.mark.parametrize("raw", ["nonsense", "=value", ":value"])
def test_parse_key_value_rejects_malformed_input(raw):
    with pytest.raises(ConfigurationError) as error:
        parse_key_value(raw, kind="query")
    assert "invalid query" in error.value.message


def test_parse_headers_builds_a_mapping():
    assert parse_headers(["Accept=application/json", "X-Trace=1"]) == {
        "Accept": "application/json",
        "X-Trace": "1",
    }


def test_parse_query_preserves_repeated_keys():
    assert parse_query(["tag=a", "tag=b", "limit=10"]) == [
        ("tag", "a"),
        ("tag", "b"),
        ("limit", "10"),
    ]


def test_parse_json_body_returns_python_objects():
    assert parse_json_body('{"name": "Alice"}') == {"name": "Alice"}


def test_parse_json_body_reports_invalid_payloads():
    with pytest.raises(ConfigurationError) as error:
        parse_json_body("{name: Alice}")
    assert "not valid JSON" in error.value.message


def test_merge_headers_overrides_case_insensitively():
    merged = merge_headers(
        {"Accept": "application/json", "Authorization": "Bearer a"},
        {"accept": "text/plain"},
    )
    assert merged == {"Authorization": "Bearer a", "accept": "text/plain"}


def test_build_request_inherits_environment_defaults(environment):
    request = build_request(environment, HttpMethod.GET, "/users")
    assert request.url == "http://localhost:8000/users"
    assert request.headers == {"Accept": "application/json"}
    assert request.timeout == 15
    assert request.verify_ssl is True
    assert request.is_safe is True


def test_build_request_applies_cli_overrides(environment):
    request = build_request(
        environment,
        HttpMethod.POST,
        "/users",
        headers={"Accept": "text/plain"},
        query=[("limit", "10")],
        json_body={"name": "Alice"},
        timeout=3,
        verify_ssl=False,
    )
    assert request.headers == {"Accept": "text/plain"}
    assert request.query == [("limit", "10")]
    assert request.json_body == {"name": "Alice"}
    assert request.timeout == 3
    assert request.verify_ssl is False
    assert request.is_safe is False


def test_build_request_rejects_two_payloads(environment):
    with pytest.raises(ConfigurationError) as error:
        build_request(
            environment,
            HttpMethod.POST,
            "/users",
            json_body={"a": 1},
            content="raw",
        )
    assert "cannot be used together" in error.value.message
