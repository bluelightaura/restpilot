"""Rendering of responses in the terminal."""

from __future__ import annotations

import io
from typing import Any

import pytest
from rich.console import Console

from restpilot.api.response_formatter import (
    MAX_TEXT_PREVIEW,
    render_response,
    status_style,
)
from restpilot.models import HttpMethod, ResponseResult

pytestmark = pytest.mark.unit


def render(result: ResponseResult, *, verbose: bool = False) -> str:
    buffer = io.StringIO()
    render_response(Console(file=buffer, width=200, color_system=None), result, verbose=verbose)
    return buffer.getvalue()


def make_result(**overrides: Any) -> ResponseResult:
    defaults: dict[str, Any] = {
        "method": HttpMethod.GET,
        "url": "http://localhost:8000/users/1",
        "status_code": 200,
        "reason_phrase": "OK",
        "headers": {"Content-Type": "application/json"},
        "body": '{"id": 1, "name": "Alice"}',
        "elapsed_ms": 42.4,
    }
    return ResponseResult(**{**defaults, **overrides})


@pytest.mark.parametrize(
    ("status", "expected"),
    [(200, "bold green"), (301, "bold cyan"), (404, "bold yellow"), (500, "bold red")],
)
def test_status_style_matches_the_status_class(status, expected):
    assert status_style(status) == expected


def test_summary_lists_the_request_facts():
    output = render(make_result())
    assert "Method:" in output and "GET" in output
    assert "http://localhost:8000/users/1" in output
    assert "Status:" in output and "200 OK" in output
    assert "Duration:" in output and "42 ms" in output
    assert "Content-Type:" in output and "application/json" in output


def test_json_body_is_pretty_printed():
    output = render(make_result())
    assert '"name": "Alice"' in output


def test_verbose_output_masks_credentials():
    output = render(
        make_result(
            request_headers={
                "Authorization": "Bearer supersecrettoken",
                "Accept": "application/json",
            },
            headers={"Content-Type": "application/json", "Set-Cookie": "session=abcdefghij"},
        ),
        verbose=True,
    )
    assert "Request headers" in output
    assert "Response headers" in output
    assert "Bearer super..." in output
    assert "supersecrettoken" not in output
    assert "session=abcdefghij" not in output


def test_headers_are_hidden_without_verbose():
    output = render(make_result(request_headers={"Authorization": "Bearer secretvalue"}))
    assert "Request headers" not in output


def test_retry_count_is_reported_when_relevant():
    assert "Attempts:" in render(make_result(attempts=3))
    assert "Attempts:" not in render(make_result())


def test_plain_text_body_is_shown_in_a_panel():
    output = render(make_result(headers={"Content-Type": "text/plain"}, body="pong"))
    assert "Body" in output and "pong" in output


def test_long_text_bodies_are_truncated():
    output = render(
        make_result(headers={"Content-Type": "text/plain"}, body="x" * (MAX_TEXT_PREVIEW + 100))
    )
    assert "truncated" in output


def test_empty_body_is_reported():
    assert "<empty body>" in render(make_result(status_code=204, body="", headers={}))


def test_invalid_json_body_is_still_displayed():
    output = render(make_result(body="{broken", headers={"Content-Type": "application/json"}))
    assert "invalid JSON" in output
    assert "{broken" in output
