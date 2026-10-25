# ROADMAP — label-notify

Status: v0.1.0 released as source on 2026-10-25. SemVer; Keep a Changelog.

## v0.1 — Walking skeleton (done)

- [x] Config schema + validator (`validate` command).
- [x] Poller with cursor + dedup + zero-write guard.
- [x] Deliveries: email, webhook, JSONL.
- [x] Mock GitHub server integration tests (L2).
- [x] Live dry-run e2e against a real public repo (L3): `microsoft/vscode`, 9 matches, 2026-10-25.
- [x] `doctor` self-check; README quickstart; CI green.

**Rate-limit spike:** one live cycle measured (anonymous 60/60 remaining before and after a single page);
the full "10 repos for 1 hour" burn measurement was **not** run. Documented math in the README: 10 repos × one
page × every 5 minutes = 120 requests/hour, which needs a token.

## v0.5 — Core value

- [x] Backoff on explicit rate-limit responses (403/429 with `X-RateLimit-Remaining: 0`); per-repo error isolation.
- [x] README kill-risks section (API deprecation, rate limits, ToS).
- [x] Multi-label OR strategy: client-side filter in one request per page (documented).
- [ ] Adaptive interval based on remaining quota (currently a fixed interval plus rate-limit wait).
- [ ] Systemd / Task Scheduler unit examples (not shipped in v0.1).
- [ ] Multi-account support.

## v1.0 — Production-ready

- [ ] L4 clean-env verification in CI; SBOM.
- [ ] Signed releases / build provenance (gate G3).
- [ ] Audit log export formats beyond JSONL (e.g., SARIF-ish).
- [ ] Optional Prometheus metrics endpoint.

## Post-1.0 (parked)

- Slack SDK convenience; GitHub App auth; webhook receiver (real-time path).

## Maintenance cadence

- API client is thin; a GitHub deprecation becomes a patch release.
- Cursor schema changes = minor version + migration note.
