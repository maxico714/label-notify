# EVIDENCE — label-notify (verified research summary)

Source: round-2 M2 verifier + ADR-002 fallback list. Ledger row 20. Access dates 2026-10-10.

## Gap class: F (exists but incomplete in a specific, nameable way)

- **IssueBell / OSS Notify:** hosted; no self-host path; privacy-egress for org activity.
- **GitHub notifications:** account-wide; no per-label filter; no custom multi-channel routing.
- **pre-commit-hooks style:** staged-only; no polling of other repos.
- No self-hosted, per-label-rule, zero-write poller found across GitHub search, PyPI, npm, AlternativeTo-style queries (round-2 M2).

## Demand hook: 4/5

- Real artifacts: GitHub community discussions on notification noise; org-wide watching pain documented in issues across busy repos.
- Cap reason (D-006): no single viral post; demand is distributed "quiet pain" (teams re-roll custom scripts). Hook sentence: "GitHub notifications are account-wide; you want per-label rules on repos you don't admin — self-hosted, zero-write, no egress."

## Host feasibility: VERIFIED

- `gh` CLI authenticated on host (`maxico714`); read-only API calls possible for e2e dry-run.
- Python 3.12 on host; no Docker needed (L4-lite fallback).
- No paid services; PAT = read-only.

## Verification story (strongest of all survivors)

Every claim is checkable with live GitHub API against public repos:
- Label events on a known repo (e.g. `bug` on a busy project) → dry-run logs correct match.
- Zero-write guard → CI test on HTTP layer.
- Rate-limit headers → measured burn rate in spike.

## Correction ledger

| Claim | Verified fact |
|---|---|
| "No label-scoped tools exist" | FALSE — IssueBell/OSS Notify exist but hosted-only (class F, not A) |
| "Real-time possible via polling" | FALSE — eventual consistency; max lag = poll interval + API latency (honest loss-bounds required) |

## Skeptic failure scenarios → binding mitigations

1. Rate limit kills polling → spike measures burn; adaptive backoff; document rate budget.
2. API deprecation / ToS → README kill-risks; thin client.
3. Polling lag unacceptable → honest loss-bounds; webhook receiver = post-1.0.
4. PAT scope creep → read-only enforced + CI test.

## Pre-mortem: "2027-04 label-notify failed"

GitHub changed API / rate limits made it useless / hosted tools added self-host / teams preferred Slack workflows → mitigation: thin client, honest docs, accept niche (self-hosted privacy-first).

## Score: round-2 survivor (N2 75; label-notify = refined framing of N2). Fallback status in ADR-002; promoted to full candidate after round-2 verification.
