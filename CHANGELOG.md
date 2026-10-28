# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security

- The plain-HTTP loopback exception now compares the parsed hostname exactly. Prefix
  matches such as `http://localhost.evil.example` and `http://127.0.0.1@evil.example`
  are rejected, so a malformed `api_base` cannot send the bearer token over plaintext
  to a remote host.

### Fixed

- Non-mapping `github` / `poll` sections and non-numeric or non-finite `poll` values now
  raise `ConfigError` (exit 1) instead of an uncaught traceback.

## [0.1.0] - 2026-10-25

First source release. Not published to PyPI.

### Added

- YAML config with repositories, label rules (`issue`/`pr`/`any`, `open`/`closed`/`any`, ANY-label match) and
  named deliveries; validation rejects invalid repos, rules, delivery references and insecure URLs.
- Read-only poller: `GET /repos/{owner}/{repo}/issues` with pagination, per-repo `since` cursor, and a bounded
  seen-ID set (10,000) for deduplication.
- Deliveries: append-only JSONL audit log, HTTPS webhook POST, and SMTP email with STARTTLS and env-based
  credentials.
- CLI: `run` (loop, `--once`, `--dry-run`), `validate`, `doctor`, `--version`; exit codes 0-5.
- Zero-write HTTP guard: GET-only, same-origin absolute URLs, HTTPS-only (localhost allowed for tests), and
  redirects refused for both GitHub and webhooks.
- Per-repository error isolation; auth failures stop the cycle; rate-limit responses stop the cycle and delay
  the next one until reset.
- Delivery-failure handling: the cursor is held so failed events are retried, while successful events are
  marked seen.

### Security

- Tokens are read from the environment only and never written to config, logs, or events; tests assert they
  do not appear in error messages.
- Plain HTTP webhook URLs and cross-origin absolute API URLs are rejected before any request is made.
- Redirects are refused to prevent an allow-listed URL from pivoting to another host.

### Verified

- 108 tests across unit, integration, security and adversarial suites (`pytest -q`).
- `ruff check`, `ruff format --check`, and strict `mypy src` clean.
- Mutation checks confirm the rule matcher, zero-write guard, and dedup tests fail when the implementation is
  broken.
- Live anonymous dry-run and a two-run dedup check against `microsoft/vscode` (9 events, 12 unique JSONL lines
  across two cycles, no duplicates).
