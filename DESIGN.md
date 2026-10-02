# Design doc — Usage Metering & Billing Engine (one page)

## Problem
Every SaaS must answer three questions: how much has this customer used, what does
it cost, and have they hit their plan limits? This service answers all three for a
small API product with two plans (Free / Pro) and two billable dimensions (API calls
+ AI tokens), with Stripe test mode for subscription management. The hard parts are
correctness puzzles, not infrastructure: exactly-once metering under retries, honest
quota boundaries (429 / 402), and real-world token pricing rules encoded in integer
money math.

## Data model
- **tenants**(id, name, api_key UNIQUE, plan_id, subscription_status) — one row per
  customer; `api_key` is the bearer credential for the metering API.
- **plans**(id, name, api_calls_quota, ai_tokens_quota, monthly_price_cents) — seeded:
  free (1,000 calls / 100k tokens / $0), pro (100k calls / 10M tokens / $49).
- **subscriptions**(id, tenant_id, provider, provider_subscription_id,
  provider_customer_id, status, plan_id) — mirrors Stripe; payment truth lives at
  the provider, this table is updated only from signature-verified webhooks.
- **usage_events**(id, tenant_id, period 'YYYY-MM', idempotency_key,
  api_calls, input_tokens, cached_input_tokens, output_tokens, reasoning_tokens,
  cost_microdollars INTEGER, response_json, created_at) —
  UNIQUE(tenant_id, idempotency_key) is the exactly-once guarantee.
- **webhook_events**(id, provider, provider_event_id UNIQUE, event_type, payload_json,
  processed_at, result) — replayed/forged events are rejected or ignored here.
- **alerts**(id, kind, message, created_at) — quota warnings + job failure alerts.

## API surface
- `POST /v1/generate` — the one dummy billable endpoint. Headers: `X-Tenant-Key`,
  `Idempotency-Key` (required). Body: token breakdown. Flow: auth → validate (4xx,
  never 500) → idempotency check (replay returns the stored response verbatim) →
  subscription check (402 if past_due/canceled) → quota check (429 if over, with a
  message naming the limit) → record event → 200 with usage + cost.
- `GET /v1/usage` — current period usage, limits, remaining, month-to-date cost.
- `POST /v1/billing/checkout` — create a Checkout session (simulated provider by
  default; real Stripe test mode when `STRIPE_SECRET_KEY` is set).
- `POST /v1/webhooks/billing` — provider webhooks. Verifies signature (HMAC for the
  simulator, `stripe.Webhook.construct_event` for Stripe), dedupes by event id,
  applies `checkout.session.completed` → Pro, `customer.subscription.updated/deleted`
  → status sync. Bad signature → 400, nothing changes.
- `POST /admin/jobs/reconcile`, `GET /admin/alerts` — the background job surface.

## Layer sketch
```
HTTP (FastAPI routers, pydantic validation at the boundary)
  -> services: metering.py (idempotent record) / quotas.py (boundary rules)
               billing.py (integer money math) / stripe_sync.py (plan sync)
  -> billing_providers/: base interface; simulated.py ($0 default);
                         stripe_provider.py (test mode, env-gated)
  -> db.py + models.py (SQLAlchemy; migrations/*.sql applied at startup)
Background: jobs.py — hourly reconciliation + quota alerts, retries + failure alerts.
```

## Money math (integers only)
All money is stored as integer **microdollars** (1e-6 USD); display rounds half-up to
cents. Pinned in `app/config.py`: input $1.50/1M tokens, cached input $0.75/1M
(cheaper), output $6.00/1M, **reasoning tokens count as output**, API call $0.0005.
Token categories are priced separately — never summed before pricing.

## Quota boundary rule (documented, probed)
`allowed` iff `current_period_usage + requested <= plan_limit`. A request landing
exactly on the limit succeeds; the next one over it fails: **429** when the
subscription is in good standing ("quota exceeded — upgrade to Pro"), **402** when
the subscription is past_due/canceled ("payment required").

## One explicit non-goal
Real payment processing and invoicing/proration/overage billing. Stripe runs in test
mode (or the built-in simulator); no real money ever moves. Those are stretch goals,
not core.
