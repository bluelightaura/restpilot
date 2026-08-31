"""The ``restpilot`` command line interface.

Every command is a thin shell: it parses arguments, delegates to the packages
under :mod:`restpilot` and renders the outcome. Expected failures surface as a
short ``Error:`` line instead of a traceback unless ``--debug`` is passed.
"""

from __future__ import annotations

import functools
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from restpilot import __version__
from restpilot.api.client import ApiClient
from restpilot.api.request_builder import (
    build_request,
    parse_headers,
    parse_json_body,
    parse_query,
)
from restpilot.api.response_formatter import render_response
from restpilot.config import LOCAL_CONFIG_NAME, ConfigPaths
from restpilot.environments.manager import EnvironmentManager
from restpilot.exceptions import ConfigurationError, RestPilotError, TestGenerationError
from restpilot.generators.coverage import CoverageReport, build_report
from restpilot.generators.pytest_generator import ensure_conftest, render_test, write_test
from restpilot.models import EnvironmentConfig, HttpMethod
from restpilot.openapi.loader import load_spec
from restpilot.openapi.parser import (
    filter_endpoints,
    find_endpoint,
    load_document,
    parse_spec,
    save_document,
)
from restpilot.utils.files import validate_writable_path, write_text
from restpilot.utils.secrets import mask_headers

F = TypeVar("F", bound=Callable[..., Any])

_NON_TTY_WIDTH = 160

console = Console(width=None if sys.stdout.isatty() else _NON_TTY_WIDTH)
error_console = Console(stderr=True, width=None if sys.stderr.isatty() else _NON_TTY_WIDTH)


@dataclass
class CliState:
    """Flags shared by every command."""

    debug: bool = False


state = CliState()


def handle_errors(command: F) -> F:
    """Turn :class:`RestPilotError` into a short message and exit code 1."""

    @functools.wraps(command)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return command(*args, **kwargs)
        except RestPilotError as error:
            if state.debug:
                raise
            error_console.print(f"[bold red]Error:[/bold red] {error.message}")
            if error.hint:
                error_console.print(f"[dim]{error.hint}[/dim]")
            raise typer.Exit(code=1) from None

    return wrapper  # type: ignore[return-value]


app = typer.Typer(
    name="restpilot",
    help="Explore, call and test REST APIs from the terminal.",
    no_args_is_help=True,
    add_completion=False,
)
env_app = typer.Typer(help="Manage environments.", no_args_is_help=True)
app.add_typer(env_app, name="env")


@app.callback()
def main(
    debug: bool = typer.Option(False, "--debug", help="Show full tracebacks on errors."),
) -> None:
    """Configure global behaviour shared by every command."""
    state.debug = debug


def _paths() -> ConfigPaths:
    return ConfigPaths.discover()


def _manager() -> EnvironmentManager:
    return EnvironmentManager(_paths())


def _parse_method(value: str) -> HttpMethod:
    try:
        return HttpMethod.parse(value)
    except ValueError as error:
        raise ConfigurationError(str(error)) from None


@app.command()
def version() -> None:
    """Show the RestPilot version."""
    console.print(f"restpilot {__version__}")


@env_app.command("create")
@handle_errors
def env_create(
    name: str = typer.Argument(..., help="Environment name, for example 'local'."),
    base_url: str = typer.Option(..., "--base-url", help="Root URL of the API."),
    timeout: float = typer.Option(10.0, "--timeout", help="Request timeout in seconds."),
    header: list[str] | None = typer.Option(
        None, "--header", "-H", help="Default header, 'Name=value'. Repeatable."
    ),
    no_verify: bool = typer.Option(False, "--no-verify", help="Disable TLS verification."),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing environment."),
    local: bool = typer.Option(
        False, "--local", help=f"Write to ./{LOCAL_CONFIG_NAME} instead of the global config."
    ),
) -> None:
    """Create an environment."""
    manager = _manager()
    target = Path.cwd() / LOCAL_CONFIG_NAME if local else None
    path = manager.create(
        name,
        base_url=base_url,
        timeout=timeout,
        verify_ssl=not no_verify,
        headers=parse_headers(header or []),
        force=force,
        target=target,
    )
    console.print(f"Created environment [bold]{name}[/bold] -> {base_url}")
    console.print(f"[dim]Saved to {path}[/dim]")


@env_app.command("list")
@handle_errors
def env_list() -> None:
    """List configured environments."""
    manager = _manager()
    config = manager.load()
    if not config.environments:
        console.print("No environments configured yet.")
        console.print(
            "[dim]Create one: restpilot env create local --base-url http://localhost:8000[/dim]"
        )
        return
    table = Table(title="Environments", title_justify="left")
    table.add_column("", width=1)
    table.add_column("NAME", style="bold")
    table.add_column("BASE URL")
    table.add_column("TIMEOUT", justify="right")
    table.add_column("SSL")
    for env_name, environment in sorted(config.environments.items()):
        marker = "*" if env_name == config.current_environment else ""
        table.add_row(
            marker,
            env_name,
            environment.base_url,
            f"{environment.timeout:g}s",
            "on" if environment.verify_ssl else "off",
        )
    console.print(table)


@env_app.command("use")
@handle_errors
def env_use(name: str = typer.Argument(..., help="Environment to select.")) -> None:
    """Select the environment used by the following commands."""
    path = _manager().use(name)
    console.print(f"Now using environment [bold]{name}[/bold]")
    console.print(f"[dim]Saved to {path}[/dim]")


@env_app.command("show")
@handle_errors
def env_show(
    name: str | None = typer.Argument(
        None, help="Environment to show. Defaults to the current one."
    ),
) -> None:
    """Show the details of an environment, with secrets masked."""
    paths = _paths()
    manager = EnvironmentManager(paths)
    if name is None:
        env_name, environment = manager.resolve()
    else:
        env_name, environment = name, manager.get(name)
    _print_environment(env_name, environment, paths)


def _print_environment(name: str, environment: EnvironmentConfig, paths: ConfigPaths) -> None:
    table = Table.grid(padding=(0, 1))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Name:", name)
    table.add_row("Base URL:", environment.base_url)
    table.add_row("Timeout:", f"{environment.timeout:g}s")
    table.add_row("Verify SSL:", "on" if environment.verify_ssl else "off")
    for index, (header_name, value) in enumerate(mask_headers(environment.headers).items()):
        table.add_row("Headers:" if index == 0 else "", f"{header_name}: {value}")
    table.add_row("Global config:", str(paths.global_config))
    table.add_row("Local config:", str(paths.local_config) if paths.local_config else "-")
    console.print(table)


@env_app.command("delete")
@handle_errors
def env_delete(name: str = typer.Argument(..., help="Environment to delete.")) -> None:
    """Delete an environment from the active configuration file."""
    path = _manager().delete(name)
    console.print(f"Deleted environment [bold]{name}[/bold]")
    console.print(f"[dim]Saved to {path}[/dim]")


@app.command("call")
@handle_errors
def call(
    method: str = typer.Argument(..., help="HTTP method, for example GET."),
    path: str = typer.Argument(..., help="Path relative to the base URL, or a full URL."),
    header: list[str] | None = typer.Option(
        None, "--header", "-H", help="Extra header, 'Name=value'. Repeatable."
    ),
    query: list[str] | None = typer.Option(
        None, "--query", "-q", help="Query parameter, 'name=value'. Repeatable."
    ),
    json_payload: str | None = typer.Option(None, "--json", "-j", help="JSON request body."),
    data: str | None = typer.Option(None, "--data", help="Raw request body."),
    timeout: float | None = typer.Option(None, "--timeout", help="Override the timeout, seconds."),
    no_verify: bool = typer.Option(False, "--no-verify", help="Disable TLS verification."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Also print headers."),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Write the response body to a file."
    ),
    expected_status: int | None = typer.Option(
        None, "--expected-status", help="Fail with exit code 1 on a different status."
    ),
    environment: str | None = typer.Option(
        None, "--env", help="Environment to use. Defaults to the selected one."
    ),
) -> None:
    """Perform an HTTP request against the current environment."""
    http_method = _parse_method(method)
    _, resolved = _manager().resolve(environment)
    request = build_request(
        resolved,
        http_method,
        path,
        headers=parse_headers(header or []),
        query=parse_query(query or []),
        json_body=parse_json_body(json_payload) if json_payload is not None else None,
        content=data,
        timeout=timeout,
        verify_ssl=False if no_verify else None,
    )
    result = ApiClient().execute(request)
    render_response(console, result, verbose=verbose)

    if output is not None:
        target = validate_writable_path(output)
        write_text(target, result.body)
        console.print(f"[dim]Body written to {target}[/dim]")

    if expected_status is not None and result.status_code != expected_status:
        error_console.print(
            f"[bold red]Error:[/bold red] expected status {expected_status}, "
            f"got {result.status_code}."
        )
        raise typer.Exit(code=1)


@app.command("import-api")
@handle_errors
def import_api(
    source: str = typer.Argument(..., help="Path or http(s) URL of an OpenAPI 3.x document."),
) -> None:
    """Import an OpenAPI specification and store its normalized form."""
    paths = _paths()
    document = parse_spec(load_spec(source), source=source)
    stored = save_document(paths.spec_path, document)
    console.print(
        f"Imported [bold]{document.title}[/bold] {document.version} "
        f"({len(document.endpoints)} endpoints)"
    )
    console.print(f"[dim]Stored in {stored}[/dim]")


@app.command("endpoints")
@handle_errors
def endpoints(
    method: str | None = typer.Option(None, "--method", "-m", help="Filter by HTTP method."),
    search: str | None = typer.Option(
        None, "--search", "-s", help="Filter by path, summary, tag or operationId."
    ),
) -> None:
    """List the endpoints of the imported specification."""
    document = load_document(_paths().spec_path)
    selected = filter_endpoints(
        document.endpoints,
        method=_parse_method(method) if method else None,
        search=search,
    )
    if not selected:
        console.print("No endpoint matches the given filters.")
        return
    table = Table(title=f"{document.title} {document.version}", title_justify="left")
    table.add_column("METHOD", style="bold cyan", no_wrap=True)
    table.add_column("PATH", no_wrap=True)
    table.add_column("SUMMARY", overflow="fold")
    for endpoint in selected:
        table.add_row(endpoint.method.value, endpoint.path, endpoint.summary)
    console.print(table)
    console.print(f"[dim]{len(selected)} of {len(document.endpoints)} endpoints[/dim]")


@app.command("coverage")
@handle_errors
def api_coverage(
    path: Path | None = typer.Option(
        None, "--path", help="Directory holding the tests. Defaults to ./generated_tests."
    ),
    missing: bool = typer.Option(False, "--missing", help="Only list endpoints without a test."),
    fail_under: float | None = typer.Option(
        None, "--fail-under", min=0, max=100, help="Exit with code 1 below this percentage."
    ),
    method: str | None = typer.Option(None, "--method", "-m", help="Filter by HTTP method."),
    search: str | None = typer.Option(None, "--search", "-s", help="Filter by path or summary."),
) -> None:
    """Show which endpoints of the imported specification already have tests."""
    paths = _paths()
    document = load_document(paths.spec_path)
    selected = filter_endpoints(
        document.endpoints,
        method=_parse_method(method) if method else None,
        search=search,
    )
    if not selected:
        console.print("No endpoint matches the given filters.")
        return
    directory = (path or paths.generated_tests_dir).expanduser()
    report = build_report(document, directory, selected)
    _print_coverage(report, missing_only=missing)

    if fail_under is not None and report.percentage < fail_under:
        error_console.print(
            f"[bold red]Error:[/bold red] endpoint coverage {report.percentage:.0f}% "
            f"is below the required {fail_under:g}%."
        )
        raise typer.Exit(code=1)


def _display_path(path: Path) -> str:
    """Shorten a path relative to the working directory when possible."""
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def _print_coverage(report: CoverageReport, *, missing_only: bool) -> None:
    entries = report.missing if missing_only else report.entries
    if entries:
        title = f"Endpoint coverage in {_display_path(report.directory)}"
        table = Table(title=title, title_justify="left")
        table.add_column("METHOD", style="bold cyan", no_wrap=True)
        table.add_column("PATH", no_wrap=True)
        table.add_column("STATUS", no_wrap=True)
        table.add_column("TEST", overflow="fold")
        for entry in entries:
            status = (
                Text("covered", style="green")
                if entry.is_covered
                else Text("missing", style="yellow")
            )
            test_file = (
                str(entry.test_file.relative_to(report.directory))
                if entry.test_file is not None and entry.test_file.is_relative_to(report.directory)
                else str(entry.test_file or "-")
            )
            table.add_row(entry.endpoint.method.value, entry.endpoint.path, status, test_file)
        console.print(table)
    elif missing_only:
        console.print("Every selected endpoint has a test.")

    console.print(
        f"[dim]{len(report.covered)} of {len(report.entries)} endpoints covered "
        f"({report.percentage:.0f}%)[/dim]"
    )
    if report.missing:
        console.print("[dim]Generate the missing ones: restpilot generate-all[/dim]")


def _base_url_for_generation(manager: EnvironmentManager) -> str:
    try:
        _, environment = manager.resolve()
    except RestPilotError:
        return ""
    return environment.base_url


@app.command("generate-test")
@handle_errors
def generate_test(
    method: str = typer.Argument(..., help="HTTP method of the endpoint."),
    path: str = typer.Argument(..., help="Path of the endpoint, as declared in OpenAPI."),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing file."),
    output_dir: Path | None = typer.Option(
        None, "--output-dir", help="Target directory. Defaults to ./generated_tests."
    ),
    smoke: bool = typer.Option(False, "--smoke", help="Also tag the test with @pytest.mark.smoke."),
) -> None:
    """Generate a pytest module for a single endpoint."""
    paths = _paths()
    manager = EnvironmentManager(paths)
    document = load_document(paths.spec_path)
    http_method = _parse_method(method)
    endpoint = find_endpoint(document, http_method, path)
    if endpoint is None:
        raise TestGenerationError(
            f"endpoint {http_method.value} {path} is not part of {document.title}.",
            hint="Use 'restpilot endpoints' to list the imported endpoints.",
        )
    target_dir = output_dir or paths.generated_tests_dir
    base_url = _base_url_for_generation(manager)
    generated = render_test(endpoint, base_url=base_url, smoke=smoke)
    ensure_conftest(target_dir, base_url)
    written = write_test(generated, target_dir, force=force)
    console.print(f"Generated [bold]{generated.test_name}[/bold] -> {written}")


@app.command("generate-all")
@handle_errors
def generate_all(
    force: bool = typer.Option(False, "--force", help="Overwrite existing files."),
    output_dir: Path | None = typer.Option(
        None, "--output-dir", help="Target directory. Defaults to ./generated_tests."
    ),
    method: str | None = typer.Option(None, "--method", "-m", help="Filter by HTTP method."),
    search: str | None = typer.Option(None, "--search", "-s", help="Filter by path or summary."),
) -> None:
    """Generate smoke tests for every imported endpoint."""
    paths = _paths()
    manager = EnvironmentManager(paths)
    document = load_document(paths.spec_path)
    selected = filter_endpoints(
        document.endpoints,
        method=_parse_method(method) if method else None,
        search=search,
    )
    if not selected:
        console.print("No endpoint matches the given filters.")
        return
    target_dir = output_dir or paths.generated_tests_dir
    base_url = _base_url_for_generation(manager)
    ensure_conftest(target_dir, base_url)

    written: list[str] = []
    skipped: list[str] = []
    used_names: set[str] = set()
    for endpoint in selected:
        generated = render_test(endpoint, base_url=base_url, smoke=True)
        generated = _deduplicate_name(generated, used_names)
        used_names.add(generated.test_name)
        try:
            path = write_test(generated, target_dir, force=force)
        except TestGenerationError:
            skipped.append(generated.file_name)
            continue
        written.append(path.name)

    console.print(f"Generated {len(written)} test(s) in {target_dir}")
    if skipped:
        console.print(
            f"[yellow]Skipped {len(skipped)} existing file(s):[/yellow] {', '.join(skipped)}"
        )
        console.print("[dim]Pass --force to overwrite them.[/dim]")


def _deduplicate_name(generated: Any, used_names: set[str]) -> Any:
    if generated.test_name not in used_names:
        return generated
    index = 2
    while f"{generated.test_name}_{index}" in used_names:
        index += 1
    new_name = f"{generated.test_name}_{index}"
    return generated.model_copy(
        update={
            "test_name": new_name,
            "file_name": f"{new_name}.py",
            "content": generated.content.replace(
                f"def {generated.test_name}(", f"def {new_name}(", 1
            ),
        }
    )


@app.command("test")
@handle_errors
def run_tests(
    path: Path | None = typer.Option(
        None, "--path", help="Directory or file to run. Defaults to ./generated_tests."
    ),
    marker: str | None = typer.Option(None, "--marker", "-m", help="Only run tests with a marker."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Run pytest in verbose mode."),
) -> None:
    """Run the generated pytest suite and propagate its exit code."""
    target = (path or _paths().generated_tests_dir).expanduser()
    if not target.exists():
        raise ConfigurationError(
            f"{target} does not exist.",
            hint="Generate tests first: restpilot generate-all.",
        )
    command = [sys.executable, "-m", "pytest", str(target)]
    if marker:
        command += ["-m", marker]
    if verbose:
        command.append("-v")
    console.print(f"[dim]$ {' '.join(command)}[/dim]")
    completed = subprocess.run(command, check=False)  # noqa: S603 - fixed argv, no shell
    raise typer.Exit(code=completed.returncode)


__all__ = ["app"]
