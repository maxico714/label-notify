# PRODUCT — label-notify

Status: v0.1.0 built and locally verified 2026-10-25 (source release; not on PyPI). Date: 2026-10-12.

## Problem

Watching a busy repo floods your GitHub notification inbox with irrelevant events. You want **only** issues/PRs that get label `security` or label `bug` + `priority:high`. GitHub's notification model has no per-label filter; webhooks require admin; hosted notifiers (IssueBell, OSS Notify) send your activity to a third party. Teams that depend on other teams' repos (monorepo orgs, open-source maintainers watching upstream) have no self-hosted, label-scoped option.

## Target users (personas)

1. **Dependency watcher (primary):** monitors upstream security/bug labels across 20+ repos; wants a Slack/email alert only when a labeled event fires. Job: reduce noise, keep signal.
2. **Org-wide triager (secondary):** cross-team issues in a large org; label rules route to the right channel. Job: route without repo-admin rights.
3. **Privacy-conscious maintainer (tertiary):** refuses hosted notifiers; wants local-only delivery. Job: keep data on-prem.

## Jobs-to-be-done

- "Notify me (email / webhook / local log) when label `security` is added to any issue in repos X, Y, Z."
- "Run this on my laptop or a cheap VM; no cloud account, no repo-admin."
- "Show me exactly what was matched and when (auditable log)."

## Value proposition (one sentence)

Self-hosted, per-label-rule GitHub notifications with zero-write enforcement — run anywhere, no admin access, no data egress to a third party.

## Non-goals (explicit)

- Not a webhook receiver (polling only in v1).
- Not a notification *aggregator* (no Slack SDK magic; webhook = plain HTTP POST).
- Not a repo-admin tool (no hooks, no settings writes).
- Not real-time (polling; eventual consistency documented).
- Not a GitHub App (PAT-based; Apps require OAuth infra).

## MVP scope (MoSCoW)

**Must (v0.1 walking skeleton):**
- Config file (YAML): list of repos + label rules (label name match, issue/PR type, optional state).
- Poller: `GET /repos/{owner}/{repo}/issues?state=all&labels=X&since=...` (or events API — decide at build time after rate-limit math); incremental `since` cursor persisted locally (JSON file).
- Deliveries: email (SMTP), webhook (HTTP POST JSON), local log (JSONL).
- Zero-write guard: HTTP layer rejects any non-GET to GitHub; CI test asserts this.
- Dedup: same event not delivered twice (cursor + event-id set).
- `--dry-run` mode (log what would be delivered).

**Should (v0.5):**
- Rate-limit-aware backoff (respect `X-RateLimit-*` headers; adaptive interval).
- Multi-account (multiple PATs) if needed.
- Systemd / Task Scheduler unit examples.
- README kill-risks section (API deprecation, rate limits, ToS).

**Could (v1.0):**
- SARIF-ish audit log; Prometheus metrics endpoint; GitHub App auth path (if demand).

**Won't (this run):** Slack SDK, real-time webhooks, repo-admin operations.

## Success criteria (measurable)

| Criterion | Measure | Command/proof |
|---|---|---|
| L1 units | Rule matcher + cursor + dedup unit tests green | `pytest -q` |
| L2 integration | Mock GitHub server: labeled event → correct delivery (email/webhook/log) | `pytest tests/integration/` |
| L3 e2e | Live dry-run against a real public repo with a known label (e.g. `bug` on a busy repo) → correct match logged | `label-notify run --dry-run --config demo.yaml` |
| L4 clean env | Fresh clone + `pip install -e .` + mock tests green | README steps in CI |
| L5 adversarial | Rate-limit 403 → backoff not crash; empty config → clean error; deleted cursor → re-scan from safe point | tests/adversarial/ |
| Honesty | README states max lag = poll interval + API latency; no "real-time" claim | manual review |
| Zero-write | CI test: HTTP layer rejects POST/PATCH/DELETE to GitHub | `pytest tests/security/` |

## Honest comparison

- **GitHub notifications:** free, account-wide, no per-label filter, no custom routing; we add label-scoped rules + multi-channel delivery.
- **IssueBell / OSS Notify:** hosted; we are self-hosted, zero-egress.
- **Zapier / IFTTT:** paid tiers, cloud lock-in; we are $0 + local.
- **Custom script:** every team re-rolls the same poller; we ship the audited, tested version.

## Naming & license

- Name `label-notify` — PyPI and npm checked 2026-10-25 (both return HTTP 404, name unused at check time); no trademark conflict found in a spot check.
- License: MIT.

## Risk register (top)

| Risk | Sev | Mitigation |
|---|---|---|
| GitHub API rate limit kills polling | High | Respect headers; adaptive backoff; document rate budget in README |
| API deprecation / ToS change | Med | README kill-risks; thin API client; easy to swap endpoint |
| Polling lag unacceptable for some use-cases | Med | Honest loss-bounds; webhook receiver = post-1.0 |
| PAT scope creep | Med | Read-only enforced in code + CI test |
