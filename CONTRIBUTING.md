# Contributing

## Setting up

```bash
git clone https://github.com/bluelightaura/restpilot.git
cd restpilot
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pre-commit install
```

## Checks

Every one of these must pass before a change is proposed. They are the same
checks CI runs, against Python 3.11, 3.12 and 3.13.

```bash
pytest
ruff check .
ruff format --check .
mypy
```

The coverage gate is 90 per cent and the suite currently sits at 99. A change
that drops coverage needs a reason stated in the pull request, not a lowered
threshold.

Tests never reach the network and never touch the real
`~/.config/restpilot`. HTTP is mocked with `respx`, and every test runs against
a temporary configuration home provided by the fixtures in `tests/conftest.py`.
Keep it that way: a test that needs a live server is a test that will fail in
somebody else's CI.

## What the code looks like

The CLI is a thin layer. `cli.py` parses arguments, delegates and renders;
anything that decides something belongs in a package under `restpilot/` where
it can be imported and tested without Typer's runner.

- Every failure is a `RestPilotError` subclass carrying a `hint`. A user who
  hits an error should be told what to do next, in the same sentence. Raw
  tracebacks are for `--debug`.
- Type annotations are complete and `mypy` runs in strict mode.
- Docstrings follow the Google convention; `ruff` enforces this.
- Secrets pass through `restpilot/utils/secrets.py`. If you add a header name
  that carries credentials, add it to `SENSITIVE_HEADERS` and cover it with a
  test — masking that is added later than the feature is masking that was
  missing in a release.

## Commits

One change per commit. The subject says what changed, in the imperative; the
body says *why* it needed changing, and what it was before. A reader six months
from now has the diff already — what they lack is the reason.

## Pull requests

State the problem before the solution, and name what you verified. If the change
touches request building, masking, file writing or the generator, say how you
exercised it beyond the unit tests: a real call against a local stub is worth
more than an assertion that mirrors the implementation.

Changes that widen what RestPilot sends, writes or prints deserve extra care.
The tool holds credentials and writes files on behalf of someone testing an
API they do not own, and both of those are easy to get subtly wrong.
