# Usage Metering & Billing Engine

**FlyRank Backend Track · Capstone C4 — "LLM Usage Metering & Billing Service"**

The service every SaaS needs: *how much has this customer used, what does it
cost, and have they hit their plan limits?* Metering, quotas, correct money
math, and Stripe-style subscription webhooks — where correctness really matters.

## What it does

- **Usage metering (exactly-once)** — `POST /v1/generate` records one usage event
  per billable action. The `Idempotency-Key` header is required; a retried request
  with the same key returns the *original* response verbatim and never double-counts
  (UNIQUE backstop + race-safe insert in `app/services/metering.py`).
- **Quota enforcement (honest boundaries)** — before any billable action:
  `current + requested <= limit` passes. The request landing *exactly* on the limit
  succeeds; the next one fails with **429** (quota exhausted, upgrade hint) or
  **402** (subscription past_due/canceled — payment required first).
- **Cost calculation (integer money math)** — all money stored as integer
  **microdollars**; display rounds half-up to cents. Pinned in `app/config.py`:
  input $1.50/1M tokens, cached input **$0.75**/1M (cheaper), output $6.00/1M,
  **reasoning tokens bill at the output rate**. Categories are priced separately —
  never summed before pricing.
- **Subscription billing (Stripe test-mode shape)** — Checkout flow +
  `checkout.session.completed` / `customer.subscription.updated` /
  `customer.subscription.deleted` webhooks. Every webhook is signature-verified,
  deduplicated by event id, and only then mirrored into the DB. Payment truth
  lives at the provider.
- **Background jobs** — hourly reconciliation (DB vs provider view, mismatches →
  alerts) and quota watch (80% warning / 100% exhausted), with retries and
  failure alerts (`POST /admin/jobs/reconcile`, `GET /admin/alerts`).

### Plans

| Plan | API calls / month | AI tokens / month | Price |
|------|------------------|-------------------|-------|
| Free | 1,000 | 100,000 | $0 |
| Pro  | 100,000 | 10,000,000 | $49/mo |

## Architecture

```
                    +-------------------+
                    |  FastAPI (app/main.py)
                    |  pydantic @ boundary -> clean 4xx, never 500
                    +--------+----------+
                             |
        +--------------------+---------------------+
        |                    |                     |
  services/            billing_providers/      jobs.py (APScheduler)
  metering.py          base.py (interface)     - reconcile (hourly)
  quotas.py            simulated.py ($0)       - quota_watch (hourly)
  billing via          stripe_provider.py      retries + failure alerts
  config.py            (test mode, env-gated)
        |                    |
        +---------+----------+
                  |
           db.py + models.py
     migrations/*.sql @ startup
     SQLite default | Postgres via DATABASE_URL
```

## Run it (a stranger in 5 minutes)

```bash
bash scripts/run.sh
# 1) creates .venv + installs deps (first run only)
# 2) applies migrations, seeds demo tenants
# 3) starts the API on http://localhost:8000
```

Demo tenants (seeded): `demo-key-123` (Free), `demo-key-456` (Pro).

```bash
# Bill one action (idempotent):
curl -s -X POST localhost:8000/v1/generate \
  -H "X-Tenant-Key: demo-key-123" -H "Idempotency-Key: $(uuidgen)" \
  -H "Content-Type: application/json" \
  -d '{"input_tokens":1000,"cached_input_tokens":500,"output_tokens":200,"reasoning_tokens":100}'

# See usage, limits, cost:
curl -s localhost:8000/v1/usage -H "X-Tenant-Key: demo-key-123"

# Simulated Pro checkout -> webhook flips Free -> Pro:
SID=$(curl -s -X POST "localhost:8000/v1/billing/checkout?plan_id=pro" \
  -H "X-Tenant-Key: demo-key-123" | python3 -c "import sys,json;print(json.load(sys.stdin)['session_id'])")
curl -s -X POST "localhost:8000/v1/billing/simulate/complete?session_id=$SID"

# Run the acceptance probes + tests:
.venv/bin/python scripts/evidence_probes.py
.venv/bin/python -m pytest -q
```

With real Stripe test mode: set `BILLING_PROVIDER=stripe`, `STRIPE_SECRET_KEY`,
`STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_PRO` in `.env` (see `.env.example`), then
`stripe listen --forward-to localhost:8000/v1/webhooks/billing`.

## Limitations (honest)

- **Billing runs on the built-in simulator by default** ($0, no account). It
  behaves like Stripe test mode and exercises the real webhook path, but no real
  Stripe account was used. The genuine Stripe SDK integration is implemented and
  documented above.
- **SQLite by default** (no Docker on the build machine); Postgres via
  `DATABASE_URL` + `docker-compose.yml`.
- **Tenant auth is a simple API key header** (`X-Tenant-Key`), not production auth.
- **Quota alerts are rows in `/admin/alerts`**, not real notifications.
- **No invoicing, proration, or overage billing** — explicit non-goals (stretch).

## Files for reviewers

- `DESIGN.md` — one-page design doc (Phase 1 gate)
- `EVIDENCE.md` — one pasted proof per requirement checkbox
- `BUILDLOG.md` — honest AI-assistance log
- `capstone.yaml` — `run:` / `seed:` / `test:` / `base_url:` manifest
