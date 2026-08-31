"""Downloading OpenAPI documents over HTTP."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from restpilot.exceptions import OpenAPIParseError
from restpilot.openapi.loader import is_url, load_spec

pytestmark = pytest.mark.integration

SPEC_URL = "https://example.com/openapi.json"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (SPEC_URL, True),
        ("http://example.com/x", True),
        ("openapi.yaml", False),
        ("./a.json", False),
    ],
)
def test_is_url_detects_remote_sources(source, expected):
    assert is_url(source) is expected


@respx.mock
def test_remote_specifications_are_downloaded(example_spec):
    payload = {"openapi": "3.0.0", "info": {"title": "Remote"}, "paths": {}}
    respx.get(SPEC_URL).mock(return_value=httpx.Response(200, text=json.dumps(payload)))
    assert load_spec(SPEC_URL) == payload
    assert example_spec.exists()


@respx.mock
def test_a_failing_download_is_reported():
    respx.get(SPEC_URL).mock(return_value=httpx.Response(404))
    with pytest.raises(OpenAPIParseError) as error:
        load_spec(SPEC_URL)
    assert "status 404" in error.value.message


@respx.mock
def test_a_download_timeout_is_reported():
    respx.get(SPEC_URL).mock(side_effect=httpx.ConnectTimeout("slow"))
    with pytest.raises(OpenAPIParseError) as error:
        load_spec(SPEC_URL, timeout=5)
    assert "timed out after 5" in error.value.message


@respx.mock
def test_an_unreachable_host_is_reported():
    respx.get(SPEC_URL).mock(side_effect=httpx.ConnectError("no route"))
    with pytest.raises(OpenAPIParseError) as error:
        load_spec(SPEC_URL)
    assert "cannot download" in error.value.message
