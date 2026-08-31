"""Rich rendering of responses, with credentials masked."""

from __future__ import annotations

import json

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from restpilot.models import ResponseResult
from restpilot.utils.secrets import mask_headers

#: Longest response body printed verbatim for non-JSON payloads.
MAX_TEXT_PREVIEW = 4000


def status_style(status_code: int) -> str:
    """Return the Rich style used for a status code."""
    if status_code < 300:
        return "bold green"
    if status_code < 400:
        return "bold cyan"
    if status_code < 500:
        return "bold yellow"
    return "bold red"


def summary_table(result: ResponseResult) -> Table:
    """Build the compact ``Method / URL / Status / Duration`` summary."""
    table = Table.grid(padding=(0, 1))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("Method:", result.method.value)
    table.add_row("URL:", result.url)
    status = Text(
        f"{result.status_code} {result.reason_phrase}".strip(),
        style=status_style(result.status_code),
    )
    table.add_row("Status:", status)
    table.add_row("Duration:", f"{result.elapsed_ms:.0f} ms")
    if result.content_type:
        table.add_row("Content-Type:", result.content_type)
    if result.attempts > 1:
        table.add_row("Attempts:", str(result.attempts))
    return table


def headers_table(title: str, headers: dict[str, str]) -> Table:
    """Build a table of headers with sensitive values masked."""
    table = Table(title=title, title_justify="left", show_edge=False, box=None, pad_edge=False)
    table.add_column("Header", style="bold cyan", no_wrap=True)
    table.add_column("Value", overflow="fold")
    for name, value in sorted(mask_headers(headers).items()):
        table.add_row(name, value)
    return table


def render_body(console: Console, result: ResponseResult) -> None:
    """Print the response body, pretty-printing and highlighting JSON."""
    if not result.body.strip():
        console.print("[dim]<empty body>[/dim]")
        return
    payload = result.json_body()
    if payload is not None or result.is_json:
        if payload is None:
            console.print(Panel(result.body[:MAX_TEXT_PREVIEW], title="Body (invalid JSON)"))
            return
        pretty = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False)
        console.print(Syntax(pretty, "json", theme="ansi_dark", word_wrap=True))
        return
    text = result.body[:MAX_TEXT_PREVIEW]
    if len(result.body) > MAX_TEXT_PREVIEW:
        text += "\n[...truncated...]"
    console.print(Panel(text, title="Body", title_align="left"))


def render_response(console: Console, result: ResponseResult, *, verbose: bool = False) -> None:
    """Print the full response report.

    Args:
        console: Target console.
        result: The executed request outcome.
        verbose: Also print request and response headers.
    """
    console.print(summary_table(result))
    if verbose:
        console.print()
        console.print(headers_table("Request headers", result.request_headers))
        console.print()
        console.print(headers_table("Response headers", result.headers))
    console.print()
    render_body(console, result)
