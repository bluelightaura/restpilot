"""pytest module generation."""

from __future__ import annotations

import pytest

from restpilot.exceptions import ConfigurationError, TestGenerationError
from restpilot.generators.pytest_generator import (
    docstring_for,
    ensure_conftest,
    python_literal,
    render_conftest,
    render_test,
    sample_path,
    snake_case,
    write_test,
)
from restpilot.generators.pytest_generator import (
    test_name_for as build_test_name,
)
from restpilot.models import HttpMethod, OpenAPIDocument, OpenAPIEndpoint, ResponseKind
from restpilot.openapi.parser import find_endpoint


def endpoint_of(document: OpenAPIDocument, method: HttpMethod, path: str) -> OpenAPIEndpoint:
    """Return an endpoint from the example document, failing loudly when absent."""
    endpoint = find_endpoint(document, method, path)
    assert endpoint is not None, f"{method.value} {path} is missing from the example spec"
    return endpoint


pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("getUser", "get_user"), ("list-users", "list_users"), ("HTTPProbe v2", "httpprobe_v2")],
)
def test_snake_case_normalizes_identifiers(raw, expected):
    assert snake_case(raw) == expected


def test_test_name_uses_the_operation_id():
    endpoint = OpenAPIEndpoint(
        method=HttpMethod.GET, path="/api/v1/users/{user_id}", operation_id="getUser"
    )
    assert build_test_name(endpoint) == "test_get_user"


def test_test_name_falls_back_to_the_path():
    endpoint = OpenAPIEndpoint(method=HttpMethod.GET, path="/api/v1/users/{user_id}")
    assert build_test_name(endpoint) == "test_get_api_v1_users_by_user_id"


def test_test_name_handles_the_root_path():
    endpoint = OpenAPIEndpoint(method=HttpMethod.GET, path="/")
    assert build_test_name(endpoint) == "test_get_root"


def test_test_name_never_starts_with_a_digit():
    endpoint = OpenAPIEndpoint(method=HttpMethod.GET, path="/health", operation_id="2fa")
    assert build_test_name(endpoint) == "test_endpoint_2fa"


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/users/{user_id}", "/users/1"),
        ("/users/{id}/roles/{roleId}", "/users/1/roles/1"),
        ("/files/{name}", "/files/example"),
        ("/health", "/health"),
    ],
)
def test_sample_path_substitutes_placeholders(path, expected):
    assert sample_path(path) == expected


def test_python_literal_uses_double_quotes_and_trailing_commas():
    rendered = python_literal({"name": "Alice", "tags": ["a"], "active": True, "note": None})
    assert '"name": "Alice",' in rendered
    assert "'" not in rendered
    assert rendered.endswith("}")


def test_python_literal_renders_empty_containers():
    assert python_literal({}) == "{}"
    assert python_literal([]) == "[]"
    assert python_literal(3) == "3"


def test_docstring_for_falls_back_to_the_endpoint():
    endpoint = OpenAPIEndpoint(method=HttpMethod.GET, path="/health")
    assert docstring_for(endpoint) == "GET /health."
    assert docstring_for(endpoint.model_copy(update={"summary": "Health probe."})) == (
        "Health probe."
    )


def test_render_test_matches_the_documented_shape(document):
    endpoint = endpoint_of(document, HttpMethod.GET, "/api/v1/users/{user_id}")
    generated = render_test(endpoint)
    assert generated.test_name == "test_get_user"
    assert generated.file_name == "test_get_user.py"
    assert "@pytest.mark.api" in generated.content
    assert "@pytest.mark.smoke" not in generated.content
    assert 'api_client.get("/api/v1/users/1")' in generated.content
    assert "assert response.status_code == 200" in generated.content
    assert "assert isinstance(body, dict)" in generated.content


def test_render_test_includes_a_request_body_example(document):
    endpoint = endpoint_of(document, HttpMethod.POST, "/api/v1/users")
    generated = render_test(endpoint, smoke=True)
    assert "@pytest.mark.smoke" in generated.content
    assert '"email": "alice@example.com",' in generated.content
    assert 'api_client.post("/api/v1/users", json=payload)' in generated.content
    assert "assert response.status_code == 201" in generated.content


def test_render_test_omits_body_assertions_for_empty_responses(document):
    endpoint = endpoint_of(document, HttpMethod.DELETE, "/api/v1/users/{user_id}")
    generated = render_test(endpoint)
    assert "assert response.status_code == 204" in generated.content
    assert "response.json()" not in generated.content


def test_render_test_accepts_dicts_or_lists_for_undocumented_bodies():
    endpoint = OpenAPIEndpoint(
        method=HttpMethod.GET, path="/things", response_kind=ResponseKind.UNKNOWN
    )
    assert "assert isinstance(body, (dict, list))" in render_test(endpoint).content


def test_render_test_ignores_a_body_example_for_safe_methods():
    endpoint = OpenAPIEndpoint(
        method=HttpMethod.GET, path="/things", request_example={"name": "Alice"}
    )
    assert "payload" not in render_test(endpoint).content


def test_write_test_refuses_to_overwrite_without_force(tmp_path, document):
    endpoint = endpoint_of(document, HttpMethod.GET, "/health")
    generated = render_test(endpoint)
    write_test(generated, tmp_path)
    with pytest.raises(TestGenerationError) as error:
        write_test(generated, tmp_path)
    assert "already exists" in error.value.message
    assert "--force" in (error.value.hint or "")


def test_write_test_overwrites_with_force(tmp_path, document):
    endpoint = endpoint_of(document, HttpMethod.GET, "/health")
    generated = render_test(endpoint)
    write_test(generated, tmp_path)
    written = write_test(
        generated.model_copy(update={"content": "# replaced\n"}), tmp_path, force=True
    )
    assert written.read_text(encoding="utf-8") == "# replaced\n"


def test_write_test_rejects_a_traversing_file_name(tmp_path, document):
    endpoint = endpoint_of(document, HttpMethod.GET, "/health")
    generated = render_test(endpoint).model_copy(update={"file_name": "../escaped.py"})
    with pytest.raises(ConfigurationError):
        write_test(generated, tmp_path)


def test_ensure_conftest_creates_the_fixture_once(tmp_path):
    first = ensure_conftest(tmp_path, "http://localhost:8000")
    first.write_text("# customized\n", encoding="utf-8")
    second = ensure_conftest(tmp_path, "http://localhost:8000")
    assert second.read_text(encoding="utf-8") == "# customized\n"


def test_render_conftest_defaults_the_base_url():
    assert 'RESTPILOT_BASE_URL", "http://localhost:8000"' in render_conftest("")
    assert "RESTPILOT_TOKEN" in render_conftest("https://stage.example.com")


def test_generated_conftest_is_valid_python(tmp_path):
    target = ensure_conftest(tmp_path, "http://localhost:8000")
    compile(target.read_text(encoding="utf-8"), str(target), "exec")


def test_generated_test_is_valid_python(tmp_path, document):
    for endpoint in document.endpoints:
        generated = render_test(endpoint, smoke=True)
        compile(generated.content, generated.file_name, "exec")
