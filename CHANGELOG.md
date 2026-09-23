# Changelog

All notable changes to RestPilot are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- `env show` no longer expands `${VAR}` placeholders. The named and unnamed
  forms printed different things for the same environment — `Bearer ${TOK...`
  against a prefix of the real credential — and the unnamed form failed
  outright when a referenced variable was unset, which is exactly the moment
  people open `env show` to find out why.
- The stored specification (`api.json`) is written owner-only, matching the
  configuration files. A specification is not a credential, but its `servers`
  block routinely names internal hosts.

### Changed

- The version is read from the installed package metadata instead of being
  repeated in `restpilot/__init__.py`, so `--version` cannot drift from
  `pyproject.toml`.
- Example payloads use `Example User` / `user@example.com`.
- Python 3.14 is declared as supported and covered by CI.

## [0.1.0] - 2026-09-01

First release.

### Added

- `env create`, `env list`, `env use`, `env show`, `env delete` — named targets
  holding a base URL, timeout, TLS setting and default headers, with a
  project-local `./.restpilot.yaml` overriding the global configuration.
- `call` — requests with query parameters, JSON or raw bodies, per-request
  timeout and header overrides, retries limited to safe methods.
- `import-api` and `endpoints` — OpenAPI 3.x loading from a file or URL, local
  `$ref` resolution, listing and searching.
- `generate-test`, `generate-all` and `test` — one pytest module per endpoint
  plus a shared `conftest.py`, and a runner that propagates pytest's exit code.
- `coverage` — imported endpoints against the tests already on disk, with
  `--fail-under` as a pipeline gate.
- Credentials stay in the process environment: configuration holds `${VAR}`
  placeholders, files are written `0600`, and sensitive headers are masked in
  every line printed.

[Unreleased]: https://github.com/bluelightaura/restpilot/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/bluelightaura/restpilot/releases/tag/v0.1.0
