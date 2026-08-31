# RestPilot

![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)
![pytest](https://img.shields.io/badge/tests-pytest-0A9EDC)
![Coverage](https://img.shields.io/badge/coverage-99%25-brightgreen)
![Ruff](https://img.shields.io/badge/lint-ruff-D7FF64)
![GitHub Actions](https://img.shields.io/badge/CI-GitHub%20Actions-2088FF)
![License](https://img.shields.io/badge/license-MIT-green)

**A CLI tool to explore, call and test REST APIs — environments, requests, OpenAPI import and
pytest generation in one command.**

---

## The problem

Testing someone else's REST API always starts with the same hour of setup:

* the base URL lives in one place, the token in another, and both change per environment;
* `curl` commands grow long and unreadable, and tokens end up in the shell history;
* the OpenAPI document lists 40 endpoints, but nobody knows which ones are already covered;
* the first pytest suite is written by hand — a client fixture, a base URL, a header, one test
  per endpoint — before a single real assertion exists.

None of that is interesting work, and all of it is repeated on every new project.

## What RestPilot does

RestPilot puts that hour into a handful of commands:

```bash
restpilot import-api openapi.yaml                  # read the contract
restpilot endpoints --search users                 # see what is available
restpilot env create local --base-url http://localhost:8000
restpilot env use local
restpilot call GET /api/v1/users/1                 # try it
restpilot generate-all                             # get a runnable pytest suite
restpilot test                                     # run it
```

It is a client for *other people's* APIs. It has no backend, no database and no server of its own.

## Features

* **Environments** — named targets (`local`, `stage`, …) with base URL, timeout, TLS verification
  and default headers; a project-local file overrides the global one.
* **No plaintext secrets** — headers use `${RESTPILOT_TOKEN}` placeholders resolved from the
  environment at request time; the config file is written with `0600` permissions.
* **Masked output** — `Authorization`, `Cookie`, `Set-Cookie` and `X-API-Key` are always truncated
  in the terminal, including in `--verbose` mode.
* **A predictable HTTP client** — query parameters, JSON or raw bodies, per-request timeout, and at
  most two retries, only for `GET`/`HEAD`/`OPTIONS` and only on network errors or `502/503/504`.
* **Readable responses** — status, duration and content type as a summary, JSON pretty-printed and
  highlighted, and `--output` to save the raw body.
* **OpenAPI 3.x import** — from a file or a URL, YAML or JSON, tolerant of unknown fields, with
  local `$ref` resolution.
* **pytest generation** — one readable module per endpoint, with the status code taken from the
  specification, an example request body when the schema provides one, and a `conftest.py`
  exposing an `api_client` fixture. Existing files are never overwritten without `--force`.
* **Endpoint coverage** — `restpilot coverage` compares the specification with the tests you
  already have and names the endpoints nobody has covered yet, with a `--fail-under` gate for CI.
* **Exit codes that mean something** — `--expected-status` and `restpilot test` propagate failures,
  so RestPilot can be used inside CI pipelines and shell scripts.

## Architecture

The CLI is a thin layer: it parses arguments, delegates, and renders. Every rule lives in a package
that can be imported and tested on its own.

```text
cli.py                    argument parsing, rendering, exit codes
├── config.py             file discovery and precedence (local over global)
├── environments/         environment CRUD, storage, ${VAR} resolution
├── api/                  request building, HTTP execution, response formatting
├── openapi/              loading (file or URL) and normalization into models
├── generators/           Jinja2 rendering of pytest modules, coverage matching
├── models.py             Pydantic models shared by every layer
├── exceptions.py         one error type per failure mode
└── utils/                secret masking and safe filesystem access
```

Failures are expressed as `RestPilotError` subclasses. The CLI turns them into a one-line
`Error:` message plus a hint — a traceback only appears with `--debug`.

## Installation

Requires Python 3.11 or newer.

```bash
git clone https://github.com/<your-account>/restpilot.git
cd restpilot
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

Check the installation:

```bash
restpilot --help
restpilot version
```

## Quick start

```bash
# 1. Point RestPilot at an API
restpilot env create local --base-url http://localhost:8000 \
  -H Accept=application/json \
  -H 'Authorization=Bearer ${RESTPILOT_TOKEN}'
restpilot env use local

# 2. Provide the token through the environment, never through the config file
export RESTPILOT_TOKEN="example-token"

# 3. Call the API
restpilot call GET /api/v1/users/1

# 4. Import the contract and generate a suite
restpilot import-api examples/openapi.yaml
restpilot endpoints
restpilot generate-all
restpilot test

# 5. Check what is still untested
restpilot coverage --missing
```

## Commands

### Environments

```bash
restpilot env create local --base-url http://localhost:8000
restpilot env create stage --base-url https://stage.example.com --timeout 20
restpilot env list
restpilot env use local
restpilot env show                # current environment, secrets masked
restpilot env delete local
```

Useful flags: `--header/-H` for default headers, `--force` to replace an existing entry,
`--local` to write `./.restpilot.yaml` instead of the global file, `--no-verify` to disable TLS
verification (off by default — verification stays on unless you ask for it).

### Requests

```bash
restpilot call GET /health
restpilot call GET /api/v1/users -q limit=10 -q offset=0 --expected-status 200
restpilot call POST /api/v1/users \
  -H Content-Type=application/json \
  -j '{"name":"Alice","email":"alice@example.com"}' \
  --expected-status 201
restpilot call DELETE /api/v1/users/1
restpilot call GET /api/v1/users/1 --output response.json
restpilot call GET /health --verbose --timeout 5
```

| Option | Meaning |
| --- | --- |
| `--header`, `-H` | Extra header, `Name=value`. Repeatable. |
| `--query`, `-q` | Query parameter, `name=value`. Repeatable, duplicates preserved. |
| `--json`, `-j` | JSON request body. |
| `--data` | Raw request body (mutually exclusive with `--json`). |
| `--timeout` | Override the environment timeout, in seconds. |
| `--no-verify` | Disable TLS certificate verification for this call. |
| `--verbose`, `-v` | Also print request and response headers, with secrets masked. |
| `--output`, `-o` | Write the response body to a file. |
| `--expected-status` | Exit with code 1 when the status differs. |
| `--env` | Use another environment for this call only. |

Output:

```text
Method:       GET
URL:          http://localhost:8000/api/v1/users/1
Status:       200 OK
Duration:     42 ms
Content-Type: application/json

{
  "id": 1,
  "name": "Alice",
  "email": "alice@example.com"
}
```

### OpenAPI

```bash
restpilot import-api examples/openapi.yaml
restpilot import-api https://example.com/openapi.json

restpilot endpoints
restpilot endpoints --method POST
restpilot endpoints --search users
```

```text
METHOD   PATH                     SUMMARY
GET      /api/v1/users            List users
POST     /api/v1/users            Create user
DELETE   /api/v1/users/{user_id}  Delete user
GET      /api/v1/users/{user_id}  Get user
GET      /health                  Service health probe
```

### Test generation

```bash
restpilot generate-test GET '/api/v1/users/{user_id}'
restpilot generate-test POST /api/v1/users --force
restpilot generate-all --method GET
restpilot test
restpilot test --marker smoke
restpilot test --path generated_tests
```

`restpilot test` runs pytest through `subprocess` with an argument list (never `shell=True`) and
returns pytest's own exit code.

### Endpoint coverage

```bash
restpilot coverage
restpilot coverage --missing
restpilot coverage --method GET --search users
restpilot coverage --path api_tests --fail-under 80
```

```text
Endpoint coverage in generated_tests
METHOD   PATH                     STATUS   TEST
GET      /api/v1/users            missing  -
POST     /api/v1/users            covered  test_create_user.py
DELETE   /api/v1/users/{user_id}  missing  -
GET      /api/v1/users/{user_id}  missing  -
GET      /health                  covered  test_health_check.py

2 of 5 endpoints covered (40%)
```

A test counts as covering an endpoint when it carries the marker RestPilot writes into the module
docstring — so renaming or editing a generated file keeps it recognized — or when it defines a
test function named the way RestPilot would name it, which lets hand-written tests count too.
`--fail-under` exits with code 1 below the given percentage, which makes the command usable as a
contract-coverage gate in a pipeline.

## Configuration

RestPilot reads two files:

1. `~/.config/restpilot/config.yaml` — the global configuration;
2. `./.restpilot.yaml` — a project file, looked up in the current directory and its parents.

The local file wins per environment name, and its `current_environment` wins as well.
`examples/restpilot.yaml` is a ready-to-copy template:

```yaml
current_environment: local

environments:
  local:
    base_url: http://localhost:8000
    timeout: 10
    verify_ssl: true
    headers:
      Accept: application/json
      Authorization: Bearer ${RESTPILOT_TOKEN}

  stage:
    base_url: https://stage.example.com
    timeout: 20
    verify_ssl: true
```

Every `${VAR}` placeholder is resolved from the process environment when a request is built. A
missing variable is a clear error, not a request sent with a literal `${VAR}` header:

```text
Error: environment variable RESTPILOT_TOKEN is referenced by the configuration but not set.
Export it before running the command, for example: export RESTPILOT_TOKEN=...
```

`RESTPILOT_CONFIG_HOME` overrides the global configuration directory, which is what the test suite
uses to stay out of your real home directory.

## Generated tests

`restpilot generate-test GET '/api/v1/users/{user_id}'` writes `generated_tests/test_get_user.py`
(see `examples/generated_test.py`):

```python
"""Generated by RestPilot for GET /api/v1/users/{user_id}.

Adjust the request data and assertions to match your scenario. RestPilot never
overwrites this file unless --force is passed.
"""

import httpx
import pytest


@pytest.mark.api
def test_get_user(api_client: httpx.Client) -> None:
    """Get user."""
    response = api_client.get("/api/v1/users/1")

    assert response.status_code == 200

    body = response.json()
    assert isinstance(body, dict)
```

The generator deliberately stays conservative: the expected status comes from the specification,
the body assertion only checks the documented shape, and no dynamic value (ids, timestamps) is
ever hard-coded into an assertion. The test name comes from `operationId` when the specification
provides one, otherwise from the method and path.

A `conftest.py` is created next to the tests on first generation and never overwritten. It reads
its configuration from the environment, so the suite stays credential-free:

```bash
export RESTPILOT_BASE_URL="http://localhost:8000"
export RESTPILOT_TOKEN="example-token"
pytest generated_tests -m smoke
```

## Project structure

```text
restpilot/
├── restpilot/
│   ├── cli.py                     Typer commands
│   ├── config.py                  configuration discovery and merging
│   ├── models.py                  Pydantic models and HttpMethod
│   ├── exceptions.py              RestPilotError hierarchy
│   ├── api/
│   │   ├── client.py              HTTPX execution, retries, timing
│   │   ├── request_builder.py     URL, headers, query and body assembly
│   │   └── response_formatter.py  Rich rendering with masked secrets
│   ├── environments/
│   │   ├── manager.py             create / use / show / delete
│   │   └── storage.py             YAML read and write
│   ├── openapi/
│   │   ├── loader.py              file and URL loading
│   │   └── parser.py              normalization into models
│   ├── generators/
│   │   ├── pytest_generator.py    rendering and safe file writing
│   │   ├── coverage.py            specification vs. existing tests
│   │   └── templates/             Jinja2 templates
│   └── utils/
│       ├── secrets.py             ${VAR} expansion and masking
│       └── files.py               atomic writes, path traversal guard
├── tests/
│   ├── unit/                      configuration, parsing, masking, generation
│   ├── integration/               HTTP behaviour through respx
│   ├── cli/                       every command through CliRunner
│   └── conftest.py                isolated config home and fixtures
├── examples/
├── .github/workflows/ci.yml
├── pyproject.toml
└── README.md
```

## Running the checks

```bash
pytest                    # 258 tests, coverage gate at 90%
ruff check .
ruff format --check .
mypy
pre-commit install        # optional: run the same checks on every commit
```

The test suite never touches the real `~/.config/restpilot`: every test runs against a temporary
configuration home. HTTP is mocked with `respx`, so no test needs a network connection.

## Continuous integration

`.github/workflows/ci.yml` runs on every push and pull request, against Python 3.11, 3.12 and
3.13: checkout, Python setup, dependency install, `ruff check`, `ruff format --check`, `mypy`,
`pytest` with coverage, and upload of `coverage.xml` as a build artifact.

## Roadmap

Not implemented in the first version, in rough order of usefulness:

* request history and replay;
* request collections (saved, named requests);
* variables carried between requests (`${response.id}`);
* JSON Schema validation of responses against the OpenAPI document;
* contract testing;
* Postman collection import;
* Allure reporting;
* load scenarios;
* a plugin system;
* a Textual TUI.

## Limitations

* OpenAPI 3.x only — Swagger 2.0 documents are rejected with a clear message.
* Only local `$ref` pointers are resolved; remote references are left untouched.
* Generated tests are scaffolding: they assert the status code and the documented body shape, not
  business rules.
* Only one specification is stored at a time per scope (project or global).
* No request history, no collections and no chaining between requests yet.
* Authentication is whatever you put in a header — there is no OAuth flow.

## Security

* Secrets are never stored in the repository or in the configuration: headers reference
  `${RESTPILOT_TOKEN}`-style placeholders resolved from the environment.
* Configuration files are written atomically with `0600` permissions.
* `Authorization`, `Proxy-Authorization`, `Cookie`, `Set-Cookie`, `X-API-Key`, `Api-Key` and
  `X-Auth-Token` are masked in every terminal output, including `--verbose`.
* `.env` is git-ignored, together with `.restpilot.yaml` and `generated_tests/`.
* `restpilot test` executes pytest with an argument list and never with `shell=True`.
* Generated files are written through a path-traversal guard that refuses absolute paths and `..`.
* Every HTTP call has a finite timeout, retries are capped at two and only for safe methods.
* TLS verification is on by default; disabling it requires an explicit `--no-verify`.

## License

[MIT](LICENSE).
