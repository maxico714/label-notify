# label-notify

**Per-label GitHub notifications you can self-host — no repo admin, no cloud middleman.**

Status: **v0.1.0 source release** (2026-10-25). Not published to PyPI yet. Tested locally on CPython 3.12
(Windows 11) and in CI on Ubuntu + Windows with Python 3.10, 3.12 and 3.13.

GitHub notifications are account-wide. Watching a busy repository means noise; ignoring it means missing the
`security` or `priority:high` label you actually care about. Webhooks need repo admin. Hosted notifiers send
your activity to a third party.

`label-notify` polls the GitHub REST API with **GET only**, matches issues and pull requests against your label
rules locally, and delivers matches to a JSONL audit log, an HTTP webhook, or email. It runs on a laptop, a
cheap VM, or a cron job. No GitHub App, no repo settings, no writes.

## What a live run looks like

Unedited output from a dry run against `microsoft/vscode` on 2026-10-25 (anonymous API, one page of 100
issues, `bug` label, 30-day window):

```text
$ label-notify doctor --config examples/demo.yaml
config: OK (1 repos, 1 rules)
token: absent (env GITHUB_TOKEN)
state: OK (C:\Users\rekha\.local\state\label-notify\demo-cursor.json)
api: reachable (rate limit 60/60 remaining)

$ label-notify run --config examples/demo.yaml --once --dry-run
note: microsoft/vscode: reached max_pages=1; older events may be skipped
dry-run: 9 matched, 0 delivered, 0 failed (repos 1)
  [dry-run] microsoft/vscode#320045 bug-watch -> events-log
  [dry-run] microsoft/vscode#334887 bug-watch -> events-log
  ...
```

A real (non-dry) run against the same repo delivered 9 events to JSONL and advanced the cursor. A second run
delivered only newly observed events — no repeats — because delivery IDs are persisted in the cursor file.

## Install

Requires Python 3.10+ and PyYAML. No paid services, no GitHub App, no admin access.

```bash
git clone https://github.com/maxico714/label-notify.git
cd label-notify
python -m venv .venv
# Windows: .venv\Scripts\activate
# POSIX:   source .venv/bin/activate
pip install -e .
```

## Quickstart

1. Copy and edit the example config:

   ```bash
   cp examples/config.yaml config.yaml
   ```

2. Validate it, then check credentials/state/API reachability:

   ```bash
   label-notify validate --config config.yaml
   label-notify doctor --config config.yaml
   ```

3. Dry-run one cycle (prints matches, writes nothing):

   ```bash
   label-notify run --config config.yaml --once --dry-run
   ```

4. Start polling (Ctrl-C to stop):

   ```bash
   label-notify run --config config.yaml
   ```

For higher rate limits, export a **read-only** token in the env var named by `github.token_env` (default
`GITHUB_TOKEN`). Public repositories work without one; private repositories need a token with read access.
The token is read from the environment only and is never written to config, logs, or events.

## Commands

| Command | Purpose |
|---|---|
| `label-notify run --config C [--once] [--dry-run]` | Poll one cycle or loop every `poll.interval_seconds` |
| `label-notify validate --config C` | Schema and cross-reference validation |
| `label-notify doctor --config C` | Token presence, state directory, live `/rate_limit` |
| `label-notify --version` | Version |

Exit codes:

| Code | Meaning |
|---|---|
| 0 | Cycle completed (dry-run included) |
| 1 | Config, cursor, or delivery-construction error (`E_CONFIG`, `E_CURSOR`) |
| 2 | Authentication rejected (`E_AUTH`) |
| 3 | Rate limited (`E_RATELIMIT`, retryable) |
| 4 | Delivery failed / partial (`E_DELIVERY`) |
| 5 | Unexpected API response (`E_API`) |

## Configuration

```yaml
github:
  token_env: GITHUB_TOKEN          # env var name; never put the token in the file
  api_base: https://api.github.com # https only (http://127.0.0.1 allowed for tests)

poll:
  interval_seconds: 300            # loop delay between cycles
  lookback_hours: 24               # cold-start window when no cursor exists
  timeout_seconds: 10              # per HTTP request
  max_pages: 5                     # 100 issues per page; cap prevents runaway scans

state_file: ~/.local/state/label-notify/cursor.json

repos:
  - pallets/flask
  - python/cpython

rules:
  - name: security-alerts
    labels: [security]             # ANY match, case-insensitive
    type: any                      # issue | pr | any
    state: any                     # open | closed | any
    deliver: [events-log, hook]

deliveries:
  events-log:
    kind: jsonl
    path: ./events.jsonl
  hook:
    kind: webhook
    url: https://hooks.example.com/label-notify
    timeout_seconds: 10
  mail:
    kind: email
    smtp_host: smtp.example.com
    smtp_port: 587
    sender: bot@example.com
    recipients: [oncall@example.com]
    starttls: true
    username_env: SMTP_USER       # credentials come from env, not YAML
    password_env: SMTP_PASS
```

Rules are OR within `labels`, AND across `type`, `state` and labels. A single issue can match several rules and
is delivered once per matching rule.

## How polling and dedup work

- One `GET /repos/{owner}/{repo}/issues?state=all&sort=updated&direction=asc&since=...&per_page=100` request
  per page, `max_pages` pages per repo per cycle. Label filtering happens client-side, because GitHub's
  `labels=` parameter cannot express OR rules in one request.
- The cursor stores a per-repo `since` timestamp and the last 10,000 delivered event IDs
  (`owner/repo#number@updated_at`). Seen IDs suppress duplicates; a new `updated_at` is a new event.
- The cursor advances only when every delivery for the repo in that cycle succeeded. A failed delivery leaves
  the cursor in place so the event is retried next cycle; successfully delivered events are still marked seen.
- Each repository is isolated: one repo failing does not stop the others. Auth failures stop the cycle;
  rate limits stop the cycle and the loop sleeps until reset (capped at 15 minutes).
- `max_pages` is an explicit truncation guard. When it is reached, a note is printed instead of silently
  skipping data. Increase it or shorten the window if you need full coverage.

## Deliveries and delivery security

- **JSONL** appends one JSON object per line: `{ts, repo, number, title, url, labels, rule, deliveries,
  delivery, status}`.
- **Webhook** sends one HTTPS POST with that JSON object. Non-HTTPS URLs are rejected (localhost is allowed for
  tests). Redirects are refused, so an allow-listed URL cannot pivot to another host. Timeouts are enforced.
- **Email** uses SMTP with STARTTLS by default; credentials come from env vars named in the config.

## Zero-write and least privilege

The HTTP client has one public method, `get()`. Any other verb raises `GuardError` before a socket opens, and
absolute URLs must stay on the configured API origin. This is covered by `tests/security/test_guard.py`, which
also asserts that a poll cycle issues only GET requests against a stub server and that tokens never appear in
error messages.

Use a fine-grained token with **read-only** repository contents/issues access, or a classic `public_repo` token
for public repositories. Do not grant write scopes.

## Honest loss bounds and rate limits

- **Not real-time.** Maximum lag is one poll interval plus API latency (plus retry time after a failure).
  With the default 300 s interval, expect up to ~5 minutes of lag.
- **The API window is `updated_at`, not label-change time.** An issue whose label is added also gets a new
  `updated_at`, so it is picked up on the next cycle; back-dated edits may not be.
- Anonymous requests are limited to **60/hour per IP**; a token raises this to **5,000/hour**. Every page is
  one request. Ten repos × one page × every 5 minutes is 120 requests/hour, which already requires a token.
  `doctor` prints the current budget; `403`/`429` with `X-RateLimit-Remaining: 0` triggers a wait until reset.
- **Eventual consistency:** a crash between delivery and cursor save can duplicate an event; a crash after
  cursor save but before delivery cannot happen by construction (the save follows delivery). JSONL is
  append-only, so downstream consumers should treat `(repo, number, rule, updated_at)` as the identity.

## Kill risks (read this before relying on it)

- **GitHub API changes** — this tool uses a thin `urllib` client over four endpoints' worth of behavior. An API
  deprecation or field rename requires a patch release; pin a version you have tested.
- **Rate-limit exhaustion** — a misconfigured interval or many repos can exhaust the budget. The tool backs off
  on explicit rate-limit responses but cannot create quota.
- **Polling is not sanctioned real-time integration.** Keep requests within GitHub's terms and your token's
  scopes. No writes, no scraping, no webhook registration.
- **Label rules are local truth.** If a team renames a label, your rule silently stops matching. Review configs
  after label taxonomy changes.
- **Single-writer state** — two processes sharing one `state_file` will race. Run one process per cursor file.

## Comparison

| Tool | What it does | Where this differs |
|---|---|---|
| GitHub notifications | Account-wide, coarse | Label-scoped rules, custom delivery, local audit log |
| GitHub webhooks | Repo-admin required | No admin rights; polling with a read-only token |
| IssueBell / OSS Notify | Hosted notification services | Self-hosted, no third-party egress |
| Zapier / IFTTT | Cloud automation | $0, local, no account, no cloud lock-in |
| A custom script | Exactly your rules | Tested matcher, dedup cursor, delivery retries, zero-write guard |

## Limitations (v0.1)

- No webhook receiver and no Slack SDK; webhook delivery is a plain JSON POST.
- Client-side label matching after fetching pages (GitHub cannot express multi-label OR server-side).
- No multi-account support; one token per process.
- Cursor file holds at most 10,000 seen IDs per repo (oldest trimmed; the `since` timestamp remains the
  primary guard).
- Not published to PyPI yet; install from source.

## Development

```bash
pip install -e ".[dev]"
ruff check src tests
ruff format --check src tests
mypy src
pytest -q
```

Layout: `src/label_notify/{config,guard,rules,cursor,deliver,poller,cli}.py`; tests are split into `unit`,
`integration`, `security`, and `adversarial`. The live dry-run example is `examples/demo.yaml`.

## License

MIT — see [LICENSE](LICENSE). Third-party notices in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
