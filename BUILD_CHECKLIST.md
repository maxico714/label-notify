# BUILD CHECKLIST — label-notify

Status: v0.1.0 complete locally on 2026-10-25 (source release). Evidence commands were run on Windows 11,
CPython 3.12.10, in a dedicated venv.

## Gate 0 — Rate-limit spike

- [x] Verify real API access with a single anonymous page and record the budget (`doctor`: 60/60 remaining).
- [x] Document the 10-repo budget math: 10 repos × one page × 5 min = 120 req/hour → token required.
- [ ] Full 1-hour, 10-repo burn measurement (NOT RUN — time-boxed; recorded as unverified in ROADMAP).

## Gate 1 — L0 static

- [x] `ruff check .` clean.
- [x] `ruff format --check .` clean.
- [x] `mypy` (strict, src) clean.

## Gate 2 — L1 units

- [x] Rule matcher (label × type × state) positive and negative tests.
- [x] Cursor load/save atomicity; deleted/corrupt cursor recovery tests.
- [x] Dedup: same event ID delivered once; new `updated_at` is a new event.
- [x] Zero-write guard: POST/PATCH/PUT/DELETE rejected before a socket opens.
- [x] **Mutation sanity:** matcher, guard, and dedup mutations each made their tests fail; sources restored and
      the full suite re-ran green.

## Gate 3 — L2 integration (mock GitHub)

- [x] Stub HTTP server: labeled issue → JSONL delivery asserted; cursor persisted.
- [x] Rate-limit 403 → exit 3, no crash, reset reported.
- [x] Partial delivery (webhook 500) → exit 4 with per-event `failed` status and JSONL still written.
- [x] Second cycle is deduplicated; delivery failure holds the cursor and retries.

## Gate 4 — L3 live e2e

- [x] Dry-run against `microsoft/vscode` with label `bug`: 9 matches logged from real API data.
- [x] Two real cycles against the same repo: 12 unique JSONL lines, no duplicate event IDs.

## Gate 5 — L5 adversarial

- [x] Empty/degenerate config → `E_CONFIG` exit 1.
- [x] 401 → `E_AUTH` exit 2; token absent from error text.
- [x] 1000-label rule, Unicode labels, hostile issue fields → no crash.
- [x] Slow webhook → timeout enforced (cycle completes in <3 s with a 0.1 s timeout).
- [x] Redirect from webhook/GitHub → refused.

## Gate 6 — Honesty and security audit

- [x] README kill-risks section present.
- [x] Loss bounds stated (poll interval + latency; no "real-time" claim).
- [x] Token env-only; grep confirms no token literals; PAT scope documented read-only.
- [x] No TODO/FIXME in `src/`.
- [x] `.agent/` and `AGENTS.md` excluded via `.gitignore`.

## Gate 7 — L4 clean environment

- [x] Wheel built, `twine check` clean, installed into a fresh venv, CLI smoke passes.
- [x] Fresh `git clone` → README install steps → `validate`, `doctor` (offline config check), `pytest` green.

## Gate 8 — Packaging (G3-gated; publishing NOT executed)

- [x] `python -m build` → wheel + sdist; `twine check` clean.
- [x] PyPI and npm both return 404 for `label-notify` (2026-10-25).
- [ ] Publish ONLY at G3 with trusted publishing (OIDC), after the G2 checklist.
