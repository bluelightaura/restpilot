# Security Policy

## Supported versions

RestPilot is currently pre-1.0. Security fixes are applied to the latest release
only.

| Version | Supported |
| --- | --- |
| 0.1.x | Yes |
| < 0.1 | No |

## Reporting a vulnerability

Do not open a public issue for anything that could expose credentials or permit
command execution. Use the repository's private reporting channel.

Include:

- affected version, Python version and operating system;
- minimal reproduction steps;
- expected and observed behavior;
- potential impact.

Never attach tokens, passwords, private keys, raw production request or response
logs, or internal hostnames and addresses. A redacted transcript is enough.

## Security boundaries

RestPilot sends what you tell it to send. It has no allow-list of targets and no
confirmation prompt, so a `DELETE` typed at the prompt is issued immediately.
Call only APIs you are authorized to call, and prefer a non-production
environment while you are still shaping a request.

Credentials are kept out of files by design. Environment headers hold
`${RESTPILOT_TOKEN}`-style placeholders that are resolved from the process
environment when a request is built; the placeholder, never the value, is what
gets written to disk. Configuration files are created atomically with `0600`
permissions, and `.env`, `.restpilot.yaml` and `generated_tests/` are
git-ignored.

`Authorization`, `Proxy-Authorization`, `Cookie`, `Set-Cookie`, `X-API-Key`,
`Api-Key` and `X-Auth-Token` are truncated in every line RestPilot prints,
including under `--verbose`.

**Response bodies are printed as received.** Masking covers headers only, so an
API that echoes your credentials back inside the payload will display them in
full; `httpbin.org/headers` does exactly that. This is a deliberate choice —
masking arbitrary JSON by key name is guesswork, and a rule that is right most
of the time teaches misplaced trust. Treat body output, and anything you paste
from it, as untrusted content.

Generated files are written through a guard that refuses absolute paths and
`..`, so a hostile `operationId` or path in a specification cannot place a file
outside the target directory. `restpilot test` invokes pytest with an argument
list and never through a shell. Every HTTP call has a finite timeout, retries
are capped at two and attempted only for safe methods, and TLS verification is
on unless `--no-verify` is passed explicitly.

RestPilot does not validate the contents of a specification beyond parsing it.
Importing a document from an untrusted URL means generating test code from
untrusted input; read what was generated before running it.
