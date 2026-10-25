# TECHNICAL — label-notify

Status: v0.1.0 built 2026-10-25. Stack: Python 3.10+; stdlib HTTP (`urllib`) + PyYAML. No paid deps.

## Architecture (C4-lite)

```
[config.yaml] → Rule engine (repos + label rules)
                       ↓
            Poller (GET issues?labels=...&since=cursor)
                       ↓
            Cursor store (local JSON: per-repo `since` + seen event-ids)
                       ↓
            Dedup filter → Delivery fan-out (email | webhook | JSONL log)
                       ↓
            Zero-write HTTP guard (rejects non-GET to GitHub)
```

Single Python package `label_notify` (CLI). No services in v1 (poller is a long-running process or cron/Task Scheduler). No DB — cursor file is the state.

## Rule model (config)

```yaml
# config.yaml
github:
  token_env: GITHUB_TOKEN        # never in file
  api_base: https://api.github.com
poll:
  interval_seconds: 300
  lookback_hours: 24             # cold-start window
repos:
  - owner/repo-a
  - owner/repo-b
rules:
  - name: security-alerts
    labels: [security]           # ANY match
    type: issue                  # issue | pr | any
    state: any                   # open | closed | any
    deliver: [webhook-main, log]
deliveries:
  webhook-main:
    kind: webhook
    url: https://hooks.example.com/x
    timeout_seconds: 10
  email-ops:
    kind: email
    smtp_host: ...
  log:
    kind: jsonl
    path: ./events.jsonl
```

Rule = (repo set × label set × type × state) → delivery list. Matching is client-side after API filter (API `labels=` is single-label; multi-label OR = multiple queries or client filter — decide at build time after rate-limit math; document choice).

## Poller semantics

- Cursor: per-repo `since` ISO timestamp + `seen` set of event-ids (bounded, e.g. last 10k).
- Cold start: `lookback_hours` window, dry-run first.
- Rate limit: read `X-RateLimit-Remaining`; sleep until reset when low; adaptive interval on 403/429.
- One repo failure ≠ crash all: per-repo error isolation, logged.

## Zero-write guard (security)

HTTP client wrapper: only `GET` allowed to `api_base`; any other method → `RuntimeError` + CI test asserts. No token in logs; redact `Authorization` header.

## Interfaces

- CLI: `label-notify run --config c.yaml [--dry-run] [--once]`; `label-notify validate --config c.yaml`; `label-notify doctor`.
- JSONL event schema: `{ts, repo, number, title, url, labels, rule, deliveries, delivery, status}`.
- Exit codes: 0 ok; 1 config/state error; 2 API auth error; 3 rate-limited (retryable); 4 delivery error (partial); 5 unexpected API response.

## Data model

Cursor file (`~/.local/state/label-notify/cursor.json` or config-specified): `{repos: {owner/repo: {since, seen: [ids]}}}`. Atomic write (temp + rename).

## Threat model (STRIDE-lite)

- Token in env only; never logged; PAT = read-only `public_repo` (or `repo` for private — documented minimum).
- Config may contain webhook URLs / SMTP creds → file permissions 0600; SMTP password via env like token.
- Webhook SSRF: allow-list schemes (https only by default); no redirects; timeout enforced.
- Polling ToS: read-only GETs within rate limits; documented in README kill-risks.
- Supply chain: stdlib-first; any third-party dep pinned + lockfile.

## Error model

Structured errors (rule-id style): `E_CONFIG`, `E_AUTH`, `E_RATELIMIT`, `E_DELIVERY`, `E_API`. Partial delivery = non-zero exit + per-delivery status in log.

## Performance budget

- Poll cycle (10 repos) < 5s wall + network.
- Memory < 50MB steady.
- Cursor file < 1MB for 10k seen events.

## Testing strategy

- L0: ruff + mypy + pytest.
- L1: rule matcher, cursor, dedup, zero-write guard unit tests.
- L2: mock GitHub HTTP server (pytest fixture) → full poll → delivery assertions.
- L3: e2e dry-run against a real public repo (host has `gh` authed — use read-only).
- L4: fresh-clone README steps in CI.
- L5: rate-limit 403, empty config, deleted cursor, huge label list, slow webhook timeout.

## Packaging

PyPI `label-notify` (verify name free at G2). GitHub Action optional (post-1.0). Systemd / Task Scheduler examples in README.

## Repo layout (target)

```
label-notify/
  src/label_notify/{config.py,poller.py,rules.py,deliver.py,cursor.py,guard.py,cli.py}
  examples/{config.yaml,systemd/,taskscheduler/}
  tests/{unit,integration,security,adversarial}/
  docs/{PRODUCT,TECHNICAL,ROADMAP,EVIDENCE}.md
```
