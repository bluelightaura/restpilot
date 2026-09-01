"""End-to-end tests of the command line interface."""

from __future__ import annotations

import importlib.util
import subprocess
from typing import Any

import httpx
import pytest
import respx
from typer.testing import CliRunner

from restpilot import __version__
from restpilot.cli import app
from restpilot.exceptions import EnvironmentNotFoundError
from tests.conftest import output_of

pytestmark = pytest.mark.cli

BASE_URL = "http://testserver"


def create_local_environment(runner: CliRunner, *extra: str) -> None:
    result = runner.invoke(app, ["env", "create", "local", "--base-url", BASE_URL, *extra])
    assert result.exit_code == 0, output_of(result)


def test_version_prints_the_package_version(runner):
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout


def test_version_flag_matches_the_subcommand(runner):
    """`--version` is what people type; the subcommand stays for scripts."""
    flag = runner.invoke(app, ["--version"])
    assert flag.exit_code == 0
    assert __version__ in flag.stdout
    assert flag.stdout == runner.invoke(app, ["version"]).stdout


def test_help_lists_every_command(runner):
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("call", "import-api", "endpoints", "generate-test", "generate-all", "env"):
        assert command in result.stdout


def test_env_create_writes_the_configuration(runner, paths):
    create_local_environment(runner)
    assert paths.global_config.exists()
    assert "local" in paths.global_config.read_text(encoding="utf-8")


def test_env_create_reports_a_duplicate_without_a_traceback(runner):
    create_local_environment(runner)
    result = runner.invoke(app, ["env", "create", "local", "--base-url", BASE_URL])
    output = output_of(result)
    assert result.exit_code == 1
    assert "Error:" in output and "already exists" in output
    assert "Traceback" not in output


def test_env_create_rejects_an_invalid_base_url(runner):
    result = runner.invoke(app, ["env", "create", "local", "--base-url", "localhost"])
    assert result.exit_code == 1
    assert "invalid environment" in output_of(result)


def test_env_create_local_writes_a_project_file(runner, project_dir):
    result = runner.invoke(app, ["env", "create", "local", "--base-url", BASE_URL, "--local"])
    assert result.exit_code == 0, output_of(result)
    assert (project_dir / ".restpilot.yaml").exists()


def test_env_list_explains_how_to_start(runner):
    result = runner.invoke(app, ["env", "list"])
    assert result.exit_code == 0
    assert "No environments configured yet." in result.stdout


def test_env_list_marks_the_current_environment(runner):
    create_local_environment(runner)
    runner.invoke(app, ["env", "create", "stage", "--base-url", "https://stage.example.com"])
    result = runner.invoke(app, ["env", "list"])
    assert result.exit_code == 0
    assert "local" in result.stdout and "stage" in result.stdout
    assert "*" in result.stdout


def test_env_use_switches_the_selection(runner):
    create_local_environment(runner)
    runner.invoke(app, ["env", "create", "stage", "--base-url", "https://stage.example.com"])
    result = runner.invoke(app, ["env", "use", "stage"])
    assert result.exit_code == 0
    assert "Now using environment" in result.stdout
    assert "stage" in runner.invoke(app, ["env", "show"]).stdout


def test_env_use_reports_an_unknown_environment(runner):
    result = runner.invoke(app, ["env", "use", "stage"])
    assert result.exit_code == 1
    assert "environment 'stage' does not exist." in output_of(result)


def test_env_show_masks_credentials(runner, monkeypatch):
    monkeypatch.setenv("RESTPILOT_TOKEN", "supersecrettoken")
    create_local_environment(runner, "-H", "Authorization=Bearer ${RESTPILOT_TOKEN}")
    result = runner.invoke(app, ["env", "show"])
    assert result.exit_code == 0
    assert "supersecrettoken" not in result.stdout
    assert "Bearer" in result.stdout


def test_env_show_accepts_an_explicit_name(runner):
    create_local_environment(runner)
    result = runner.invoke(app, ["env", "show", "local"])
    assert result.exit_code == 0
    assert BASE_URL in result.stdout


def test_env_delete_removes_the_environment(runner):
    create_local_environment(runner)
    result = runner.invoke(app, ["env", "delete", "local"])
    assert result.exit_code == 0
    assert "No environments configured yet." in runner.invoke(app, ["env", "list"]).stdout


def test_env_delete_reports_an_unknown_environment(runner):
    result = runner.invoke(app, ["env", "delete", "ghost"])
    assert result.exit_code == 1
    assert "does not exist" in output_of(result)


@respx.mock
def test_call_performs_a_get_request(runner):
    create_local_environment(runner)
    respx.get(f"{BASE_URL}/users/1").mock(
        return_value=httpx.Response(200, json={"id": 1, "name": "Alice"})
    )
    result = runner.invoke(app, ["call", "GET", "/users/1"])
    assert result.exit_code == 0, output_of(result)
    assert "200 OK" in result.stdout
    assert '"name": "Alice"' in result.stdout


@respx.mock
def test_call_sends_query_parameters_and_checks_the_status(runner):
    create_local_environment(runner)
    route = respx.get(f"{BASE_URL}/users").mock(return_value=httpx.Response(200, json=[]))
    result = runner.invoke(
        app,
        ["call", "GET", "/users", "-q", "limit=10", "-q", "offset=0", "--expected-status", "200"],
    )
    assert result.exit_code == 0, output_of(result)
    assert str(route.calls.last.request.url).endswith("?limit=10&offset=0")


@respx.mock
def test_call_posts_a_json_body(runner):
    create_local_environment(runner)
    route = respx.post(f"{BASE_URL}/users").mock(return_value=httpx.Response(201, json={"id": 3}))
    result = runner.invoke(
        app,
        [
            "call",
            "POST",
            "/users",
            "-H",
            "Content-Type=application/json",
            "-j",
            '{"name":"Alice"}',
            "--expected-status",
            "201",
        ],
    )
    assert result.exit_code == 0, output_of(result)
    assert route.calls.last.request.content == b'{"name":"Alice"}'


@respx.mock
def test_call_fails_on_an_unexpected_status(runner):
    create_local_environment(runner)
    respx.get(f"{BASE_URL}/users/1").mock(return_value=httpx.Response(404, json={}))
    result = runner.invoke(app, ["call", "GET", "/users/1", "--expected-status", "200"])
    assert result.exit_code == 1
    assert "expected status 200, got 404" in output_of(result)


@respx.mock
def test_call_writes_the_body_to_a_file(runner, project_dir):
    create_local_environment(runner)
    respx.get(f"{BASE_URL}/users/1").mock(return_value=httpx.Response(200, json={"id": 1}))
    result = runner.invoke(app, ["call", "GET", "/users/1", "-o", "response.json"])
    assert result.exit_code == 0, output_of(result)
    assert (project_dir / "response.json").read_text(encoding="utf-8") == '{"id":1}'


@respx.mock
def test_call_masks_the_token_in_verbose_mode(runner, monkeypatch):
    monkeypatch.setenv("RESTPILOT_TOKEN", "supersecrettoken")
    create_local_environment(runner, "-H", "Authorization=Bearer ${RESTPILOT_TOKEN}")
    respx.get(f"{BASE_URL}/health").mock(return_value=httpx.Response(200, json={"status": "ok"}))
    result = runner.invoke(app, ["call", "GET", "/health", "--verbose"])
    assert result.exit_code == 0, output_of(result)
    assert "Request headers" in result.stdout
    assert "supersecrettoken" not in result.stdout


def test_call_rejects_an_unsupported_method(runner):
    create_local_environment(runner)
    result = runner.invoke(app, ["call", "TRACE", "/users"])
    assert result.exit_code == 1
    assert "unsupported HTTP method" in output_of(result)


def test_call_rejects_an_invalid_json_payload(runner):
    create_local_environment(runner)
    result = runner.invoke(app, ["call", "POST", "/users", "-j", "{name: Alice}"])
    assert result.exit_code == 1
    assert "not valid JSON" in output_of(result)


def test_call_requires_a_selected_environment(runner):
    result = runner.invoke(app, ["call", "GET", "/users"])
    assert result.exit_code == 1
    assert "no environment is selected." in output_of(result)


def test_debug_flag_surfaces_the_traceback(runner):
    result = runner.invoke(app, ["--debug", "env", "use", "ghost"])
    assert result.exit_code == 1
    assert isinstance(result.exception, EnvironmentNotFoundError)


def test_missing_arguments_are_reported_by_typer(runner):
    result = runner.invoke(app, ["call", "GET"])
    assert result.exit_code == 2
    assert "Missing argument" in output_of(result)


def test_import_api_stores_the_specification(runner, paths, example_spec):
    result = runner.invoke(app, ["import-api", str(example_spec)])
    assert result.exit_code == 0, output_of(result)
    assert "Demo Users API" in result.stdout
    assert paths.spec_path.exists()


def test_import_api_reports_a_missing_file(runner, project_dir):
    result = runner.invoke(app, ["import-api", str(project_dir / "nope.yaml")])
    assert result.exit_code == 1
    assert "does not exist" in output_of(result)


def test_endpoints_lists_the_imported_operations(runner, imported_spec):
    result = runner.invoke(app, ["endpoints"])
    assert result.exit_code == 0, output_of(result)
    assert "METHOD" in result.stdout and "/api/v1/users" in result.stdout
    assert "5 of 5 endpoints" in result.stdout


def test_endpoints_filters_by_method_and_search(runner, imported_spec):
    by_method = runner.invoke(app, ["endpoints", "--method", "POST"])
    by_search = runner.invoke(app, ["endpoints", "--search", "health"])
    assert "1 of 5 endpoints" in by_method.stdout
    assert "/health" in by_search.stdout


def test_endpoints_reports_an_empty_selection(runner, imported_spec):
    result = runner.invoke(app, ["endpoints", "--search", "nothing-matches"])
    assert result.exit_code == 0
    assert "No endpoint matches" in result.stdout


def test_endpoints_requires_an_import(runner):
    result = runner.invoke(app, ["endpoints"])
    assert result.exit_code == 1
    assert "no OpenAPI specification has been imported yet." in output_of(result)


def test_generate_test_writes_a_module(runner, imported_spec, project_dir):
    create_local_environment(runner)
    result = runner.invoke(app, ["generate-test", "GET", "/api/v1/users/{user_id}"])
    assert result.exit_code == 0, output_of(result)
    generated = project_dir / "generated_tests" / "test_get_user.py"
    assert "def test_get_user(api_client: httpx.Client)" in generated.read_text(encoding="utf-8")
    assert (project_dir / "generated_tests" / "conftest.py").exists()


def test_generate_test_refuses_to_overwrite(runner, imported_spec):
    runner.invoke(app, ["generate-test", "GET", "/health"])
    result = runner.invoke(app, ["generate-test", "GET", "/health"])
    assert result.exit_code == 1
    assert "--force" in output_of(result)
    assert runner.invoke(app, ["generate-test", "GET", "/health", "--force"]).exit_code == 0


def test_generate_test_reports_an_unknown_endpoint(runner, imported_spec):
    result = runner.invoke(app, ["generate-test", "GET", "/unknown"])
    assert result.exit_code == 1
    assert "is not part of" in output_of(result)


def test_generate_all_covers_every_endpoint(runner, imported_spec, project_dir):
    result = runner.invoke(app, ["generate-all"])
    assert result.exit_code == 0, output_of(result)
    generated = sorted(path.name for path in (project_dir / "generated_tests").glob("test_*.py"))
    assert generated == [
        "test_create_user.py",
        "test_delete_user.py",
        "test_get_user.py",
        "test_health_check.py",
        "test_list_users.py",
    ]
    assert "Generated 5 test(s)" in result.stdout


def test_generate_all_skips_existing_files(runner, imported_spec):
    runner.invoke(app, ["generate-all"])
    result = runner.invoke(app, ["generate-all"])
    assert result.exit_code == 0
    assert "Skipped 5 existing file(s)" in result.stdout


def test_generate_all_respects_filters(runner, imported_spec, project_dir):
    result = runner.invoke(app, ["generate-all", "--method", "GET", "--search", "health"])
    assert result.exit_code == 0, output_of(result)
    assert [path.name for path in (project_dir / "generated_tests").glob("test_*.py")] == [
        "test_health_check.py"
    ]


def test_generate_all_reports_an_empty_selection(runner, imported_spec):
    result = runner.invoke(app, ["generate-all", "--search", "nothing"])
    assert result.exit_code == 0
    assert "No endpoint matches" in result.stdout


def test_generate_all_deduplicates_test_names(runner, paths, project_dir):
    from restpilot.models import HttpMethod, OpenAPIDocument, OpenAPIEndpoint
    from restpilot.openapi.parser import save_document

    document = OpenAPIDocument(
        title="Colliding API",
        version="1.0.0",
        endpoints=[
            OpenAPIEndpoint(method=HttpMethod.GET, path="/a", operation_id="probe"),
            OpenAPIEndpoint(method=HttpMethod.GET, path="/b", operation_id="probe"),
        ],
    )
    save_document(paths.spec_path, document)
    result = runner.invoke(app, ["generate-all"])
    assert result.exit_code == 0, output_of(result)
    names = sorted(path.name for path in (project_dir / "generated_tests").glob("test_*.py"))
    assert names == ["test_probe.py", "test_probe_2.py"]
    assert "def test_probe_2(" in (project_dir / "generated_tests" / "test_probe_2.py").read_text(
        encoding="utf-8"
    )


def test_test_command_requires_generated_tests(runner):
    result = runner.invoke(app, ["test"])
    assert result.exit_code == 1
    assert "restpilot generate-all" in output_of(result)


def test_test_command_runs_pytest_without_a_shell(runner, imported_spec, project_dir, monkeypatch):
    runner.invoke(app, ["generate-all"])
    captured: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, returncode=3)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = runner.invoke(app, ["test", "--marker", "smoke", "--verbose"])

    assert result.exit_code == 3
    command = captured["command"]
    assert command[1:3] == ["-m", "pytest"]
    assert command[-3:] == ["-m", "smoke", "-v"]
    assert str(project_dir / "generated_tests") in command
    assert "shell" not in captured["kwargs"]


def test_test_command_accepts_an_explicit_path(runner, project_dir, monkeypatch):
    target = project_dir / "api_tests"
    target.mkdir()
    monkeypatch.setattr(
        subprocess, "run", lambda command, **kwargs: subprocess.CompletedProcess(command, 0)
    )
    result = runner.invoke(app, ["test", "--path", str(target)])
    assert result.exit_code == 0


def test_test_command_reports_a_missing_pytest(runner, imported_spec, monkeypatch):
    runner.invoke(app, ["generate-all"])
    real_find_spec = importlib.util.find_spec

    def fake_find_spec(name: str, *args: Any, **kwargs: Any) -> Any:
        return None if name == "pytest" else real_find_spec(name, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)
    result = runner.invoke(app, ["test"])

    assert result.exit_code == 1
    assert "pytest is not installed" in output_of(result)
    assert "pipx inject restpilot pytest" in output_of(result)


def test_coverage_reports_generated_tests(runner, imported_spec, project_dir):
    runner.invoke(app, ["generate-test", "GET", "/health"])
    result = runner.invoke(app, ["coverage"])
    assert result.exit_code == 0, output_of(result)
    assert "covered" in result.stdout and "missing" in result.stdout
    assert "test_health_check.py" in result.stdout
    assert "1 of 5 endpoints covered (20%)" in result.stdout
    assert "restpilot generate-all" in result.stdout


def test_coverage_lists_only_the_gaps(runner, imported_spec):
    runner.invoke(app, ["generate-test", "GET", "/health"])
    result = runner.invoke(app, ["coverage", "--missing"])
    assert result.exit_code == 0, output_of(result)
    assert "/health" not in result.stdout
    assert "/api/v1/users" in result.stdout


def test_coverage_confirms_a_complete_suite(runner, imported_spec):
    runner.invoke(app, ["generate-all"])
    result = runner.invoke(app, ["coverage", "--missing"])
    assert result.exit_code == 0, output_of(result)
    assert "Every selected endpoint has a test." in result.stdout
    assert "5 of 5 endpoints covered (100%)" in result.stdout


def test_coverage_gate_fails_below_the_threshold(runner, imported_spec):
    runner.invoke(app, ["generate-test", "GET", "/health"])
    result = runner.invoke(app, ["coverage", "--fail-under", "50"])
    assert result.exit_code == 1
    assert "coverage 20% is below the required 50%" in output_of(result)


def test_coverage_gate_passes_when_the_suite_is_complete(runner, imported_spec):
    runner.invoke(app, ["generate-all"])
    assert runner.invoke(app, ["coverage", "--fail-under", "100"]).exit_code == 0


def test_coverage_accepts_filters_and_an_explicit_path(runner, imported_spec, project_dir):
    target = project_dir / "api_tests"
    runner.invoke(app, ["generate-all", "--output-dir", str(target)])
    result = runner.invoke(
        app, ["coverage", "--path", str(target), "--method", "GET", "--search", "health"]
    )
    assert result.exit_code == 0, output_of(result)
    assert "1 of 1 endpoints covered (100%)" in result.stdout


def test_coverage_reports_an_empty_selection(runner, imported_spec):
    result = runner.invoke(app, ["coverage", "--search", "nothing-matches"])
    assert result.exit_code == 0
    assert "No endpoint matches" in result.stdout


def test_coverage_requires_an_import(runner):
    result = runner.invoke(app, ["coverage"])
    assert result.exit_code == 1
    assert "no OpenAPI specification has been imported yet." in output_of(result)


def test_coverage_shortens_the_directory_in_the_title(runner, imported_spec):
    runner.invoke(app, ["generate-all"])
    result = runner.invoke(app, ["coverage"])
    assert "Endpoint coverage in generated_tests" in result.stdout
