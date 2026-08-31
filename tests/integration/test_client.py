"""HTTP client behaviour against a mocked transport."""

from __future__ import annotations

import httpx
import pytest
import respx

from restpilot.api.client import MAX_RETRIES, ApiClient, RetryPolicy
from restpilot.api.request_builder import build_request
from restpilot.exceptions import RequestExecutionError
from restpilot.models import EnvironmentConfig, HttpMethod

pytestmark = pytest.mark.integration

BASE_URL = "http://testserver"


@pytest.fixture
def environment():
    return EnvironmentConfig(base_url=BASE_URL, headers={"Accept": "application/json"})


@pytest.fixture
def client():
    return ApiClient(retry_policy=RetryPolicy(backoff_seconds=0.0), sleep=lambda _: None)


@respx.mock
def test_successful_get_returns_a_parsed_result(client, environment):
    route = respx.get(f"{BASE_URL}/users/1").mock(
        return_value=httpx.Response(200, json={"id": 1, "name": "Alice"})
    )
    result = client.execute(build_request(environment, HttpMethod.GET, "/users/1"))

    assert route.called
    assert result.status_code == 200
    assert result.method is HttpMethod.GET
    assert result.json_body() == {"id": 1, "name": "Alice"}
    assert result.is_json
    assert result.attempts == 1
    assert result.elapsed_ms >= 0


@respx.mock
def test_successful_post_sends_the_json_body(client, environment):
    route = respx.post(f"{BASE_URL}/users").mock(return_value=httpx.Response(201, json={"id": 3}))
    result = client.execute(
        build_request(environment, HttpMethod.POST, "/users", json_body={"name": "Alice"})
    )

    assert result.status_code == 201
    request = route.calls.last.request
    assert request.content == b'{"name":"Alice"}'
    assert request.headers["content-type"] == "application/json"


@respx.mock
def test_raw_data_is_sent_untouched(client, environment):
    route = respx.put(f"{BASE_URL}/notes/1").mock(return_value=httpx.Response(200))
    client.execute(build_request(environment, HttpMethod.PUT, "/notes/1", content="plain body"))
    assert route.calls.last.request.content == b"plain body"


@respx.mock
def test_environment_headers_and_query_parameters_are_applied(client, environment):
    route = respx.get(f"{BASE_URL}/users").mock(return_value=httpx.Response(200, json=[]))
    client.execute(
        build_request(
            environment,
            HttpMethod.GET,
            "/users",
            headers={"X-Trace": "42"},
            query=[("limit", "10"), ("offset", "0")],
        )
    )
    request = route.calls.last.request
    assert request.headers["accept"] == "application/json"
    assert request.headers["x-trace"] == "42"
    assert str(request.url) == f"{BASE_URL}/users?limit=10&offset=0"


@respx.mock
def test_text_response_is_reported_without_json(client, environment):
    respx.get(f"{BASE_URL}/health").mock(
        return_value=httpx.Response(200, text="pong", headers={"Content-Type": "text/plain"})
    )
    result = client.execute(build_request(environment, HttpMethod.GET, "/health"))
    assert result.body == "pong"
    assert not result.is_json
    assert result.json_body() is None


@respx.mock
def test_unexpected_status_is_returned_not_raised(client, environment):
    respx.get(f"{BASE_URL}/users/999").mock(
        return_value=httpx.Response(404, json={"detail": "not found"})
    )
    result = client.execute(build_request(environment, HttpMethod.GET, "/users/999"))
    assert result.status_code == 404
    assert result.json_body() == {"detail": "not found"}


@respx.mock
def test_timeout_raises_a_request_execution_error(client, environment):
    respx.get(f"{BASE_URL}/slow").mock(side_effect=httpx.ReadTimeout("too slow"))
    with pytest.raises(RequestExecutionError) as error:
        client.execute(build_request(environment, HttpMethod.GET, "/slow", timeout=1))
    assert "timed out after 1" in error.value.message
    assert "--timeout" in (error.value.hint or "")


@respx.mock
def test_connection_error_raises_a_request_execution_error(client, environment):
    respx.post(f"{BASE_URL}/users").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(RequestExecutionError) as error:
        client.execute(build_request(environment, HttpMethod.POST, "/users", json_body={}))
    assert "cannot reach" in error.value.message


@respx.mock
def test_get_is_retried_on_a_gateway_error(client, environment):
    route = respx.get(f"{BASE_URL}/users").mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(502),
            httpx.Response(200, json=[]),
        ]
    )
    result = client.execute(build_request(environment, HttpMethod.GET, "/users"))
    assert route.call_count == 3
    assert result.status_code == 200
    assert result.attempts == 3


@respx.mock
def test_retries_stop_after_the_hard_limit(client, environment):
    route = respx.get(f"{BASE_URL}/users").mock(return_value=httpx.Response(503))
    result = client.execute(build_request(environment, HttpMethod.GET, "/users"))
    assert route.call_count == MAX_RETRIES + 1
    assert result.status_code == 503


@respx.mock
def test_get_is_retried_on_a_network_error(client, environment):
    route = respx.get(f"{BASE_URL}/users").mock(
        side_effect=[httpx.ConnectError("boom"), httpx.Response(200, json=[])]
    )
    result = client.execute(build_request(environment, HttpMethod.GET, "/users"))
    assert route.call_count == 2
    assert result.attempts == 2


@respx.mock
def test_post_is_never_retried(client, environment):
    route = respx.post(f"{BASE_URL}/users").mock(return_value=httpx.Response(503))
    result = client.execute(build_request(environment, HttpMethod.POST, "/users", json_body={}))
    assert route.call_count == 1
    assert result.attempts == 1


@respx.mock
def test_delete_is_never_retried_on_a_network_error(client, environment):
    route = respx.delete(f"{BASE_URL}/users/1").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(RequestExecutionError):
        client.execute(build_request(environment, HttpMethod.DELETE, "/users/1"))
    assert route.call_count == 1


@respx.mock
def test_head_requests_are_supported(client, environment):
    respx.head(f"{BASE_URL}/health").mock(return_value=httpx.Response(200))
    result = client.execute(build_request(environment, HttpMethod.HEAD, "/health"))
    assert result.status_code == 200
    assert result.body == ""


def test_retry_policy_never_exceeds_the_hard_limit():
    policy = RetryPolicy(max_retries=99)
    safe = build_request(EnvironmentConfig(base_url=BASE_URL), HttpMethod.GET, "/x")
    unsafe = build_request(EnvironmentConfig(base_url=BASE_URL), HttpMethod.PATCH, "/x")
    assert policy.attempts_for(safe) == MAX_RETRIES + 1
    assert policy.attempts_for(unsafe) == 1


@respx.mock
def test_backoff_is_applied_between_attempts(environment):
    delays: list[float] = []
    client = ApiClient(retry_policy=RetryPolicy(backoff_seconds=0.5), sleep=delays.append)
    respx.get(f"{BASE_URL}/users").mock(return_value=httpx.Response(504))
    client.execute(build_request(environment, HttpMethod.GET, "/users"))
    assert delays == [0.5, 1.0]


@respx.mock
def test_redirects_are_followed(client, environment):
    respx.get(f"{BASE_URL}/old").mock(
        return_value=httpx.Response(307, headers={"Location": f"{BASE_URL}/new"})
    )
    respx.get(f"{BASE_URL}/new").mock(return_value=httpx.Response(200, json={"ok": True}))
    result = client.execute(build_request(environment, HttpMethod.GET, "/old"))
    assert result.status_code == 200
    assert result.url == f"{BASE_URL}/new"
