# BUILDLOG.md — honest log of how this capstone was built

Built 2026-10-01 by Qiwei Li's agent (Muse), delegated by Qiwei to finish the
FlyRank backend track. AI-assisted building is encouraged by the brief — this log
is where that assistance is owned, per Ground Rule 4.

## Where AI helped
- Scaffolding: project layout, FastAPI route wiring, SQLAlchemy models, the SQL
  migrations, and the pytest/evidence-probe harnesses were drafted by the agent
  from the capstone brief (Sections 2–12, read in full from the portal PDF).
- Design decisions below were made deliberately and verified by running code,
  not trusted on generation.

## Where AI was wrong / what changed
1. **Relative imports**: first draft used `from . import config` inside
   `app/services/` (wrong package level). Fixed to `from .. import config`, then
   over-corrected one same-package import (`from .metering`) — fixed back. Caught
   by pytest collection, fixed before any commit that mattered.
2. **Plan object vs dict**: `check_quotas` was written against a `Plan` model but
   called with a `config.PLANS` dict (`AttributeError: 'dict' object has no
   attribute 'api_calls_quota'`). Fixed by making the service take the config
   dict explicitly. Caught by tests.
3. **Probe 5 over-quota**: my first evidence script sent 10 × 1.8M tokens against
   the Pro 10M quota — the service correctly 429'd half of them. The *service*
   was right; the *script* was wrong. Resized the probe and re-ran: all 5 pass.
4. **No Docker on the build machine**: the brief's $0 stack lists "PostgreSQL via
   Docker (or SQLite)". Docker isn't available here, so the default is SQLite via
   `DATABASE_URL`; a `docker-compose.yml` is included for Postgres parity and the
   migrator works on both. Documented in README "Limitations" — not hidden.

## Key decisions (mine to explain)
- **Simulated billing provider by default.** Creating a real Stripe account needs
  the user's identity; the brief's Q&A explicitly blesses simulating billing, and
  Section 7 says "You do not need real payments". The simulator delivers through
  the *same* signature-verified webhook endpoint as real Stripe, so verification,
  dedup, and plan-sync are genuinely exercised. The real Stripe SDK path is fully
  implemented (`stripe_provider.py`, test-mode only, live keys refused) and
  activates with `STRIPE_SECRET_KEY`. This trade-off is stated in README and
  EVIDENCE.md — no claim is made that isn't true.
- **Boundary rule**: `current + requested <= limit` passes; the request landing
  exactly on the limit succeeds (documented in DESIGN.md, proven in PROBE 2).
- **Money as integer microdollars**, truncation at the microdollar, half-up to
  cents for display. Small amounts (1 token = 1μ$) stay exact; evidence totals
  match because probes use the same functions as the API.

## Verification
- `pytest`: 13/13 passing (money math, idempotency, quota boundary, webhooks,
  402 gating, 4xx-not-500).
- `scripts/evidence_probes.py`: all 5 acceptance probes PASS against the live app.
- I can explain any 2–3 lines a reviewer picks: the idempotency pre-check +
  UNIQUE backstop in `services/metering.py`, the boundary comparison in
  `services/quotas.py`, and the integer pricing in `config.py`.
