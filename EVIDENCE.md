# EVIDENCE.md — one pasted proof per Section 6 requirement box

Generated 2026-10-01 by `scripts/evidence_probes.py` (real output from the running
service, isolated throwaway DB) plus `pytest` (13 tests). Reproduce any of it with:

```bash
.venv/bin/python scripts/evidence_probes.py
.venv/bin/python -m pytest -q
```

---

## Metering

- [x] **A billable action creates exactly one usage event, even under retries —
  deduplicated by idempotency key.**

```
PROBE 1 — same billable request twice, one idempotency key
first  -> 200 replayed=False
second -> 200 replayed=True
responses identical: True
api_calls used after 2 sends: 1 (must be 1)
PROBE 1: PASS
```

- [x] **Proof that double-counting cannot happen** — same request sent twice;
  `UNIQUE(tenant_id, idempotency_key)` is the backstop and a lost race still
  returns the winner (`test_same_request_twice_one_event`, pytest). The replayed
  response mirrors the original byte-for-byte (`responses identical: True`).

## Quotas

- [x] **Usage is checked against the tenant's plan; requests over the limit are
  rejected.**

- [x] **Correct status codes (429 / 402) with a message explaining why.**

```
PROBE 2 — drive to the exact quota boundary (Free: 1000 calls)
request #1000 (exactly at limit) -> 200 (must be 200)
request #1001 (over limit)      -> 429 (must be 429)
message: api_calls quota exceeded on the 'free' plan: already used 1000, this
request needs 1, limit is 1000 per month. Upgrade to Pro for higher limits or
wait for the next billing period.
PROBE 2: PASS
```

402 proof (`test_subscription_deleted_downgrades`, pytest): after
`customer.subscription.deleted`, `POST /v1/generate` → `402 payment_required`
with *"Payment required: your subscription status is 'canceled', so billable
actions are paused…"* — payment status gates billing before quota does.

## Cost calculation

- [x] **Monthly usage rolls up into a cost figure per tenant** (`GET /v1/usage`).

- [x] **AI token pricing handles cached input tokens, reasoning tokens, and
  output pricing correctly** — cached input is cheaper ($0.75 vs $1.50/1M),
  reasoning tokens bill at the output rate ($6.00/1M); categories are priced
  separately, never summed before pricing (`test_money.py`, all passing).

- [x] **Pricing constants pinned in config, with proof of correct totals.**

```
PROBE 5 — pinned pricing rules produce exact totals
per-event microdollars: 368000 (= 100k*1.50 + 50k*0.75 + 30k*6.00 + 1 call*0.0005)
GET /usage cost_microdollars: 3680000
expected (10 events):          3680000
display: $3.68
PROBE 5: PASS
```

Constants live in `app/config.py` (`PRICE_*`); all money is integer microdollars,
display rounds half-up to cents (`ud_to_dollars_str`).

## Stripe integration

- [x] **Subscription checkout works end-to-end** — verified against the built-in
  simulated provider, which behaves like Stripe test mode ($0, no account) and
  delivers through the same signature-verified webhook endpoint as real Stripe
  events. The real Stripe SDK integration (`app/billing_providers/stripe_provider.py`,
  test mode only, live keys refused) is implemented and activates when
  `STRIPE_SECRET_KEY` is set; see README "Limitations" for the honest trade-off.

```
PROBE 3 — Stripe-style test checkout flips Free -> Pro via webhook
before: plan=free token_quota=100000
checkout session: cs_sim_c8658f1e66f8428e
webhook result: tenant_upgraded_to:pro
after:  plan=pro token_quota=10000000
PROBE 3: PASS
```

- [x] **Webhooks verify signatures, ignore duplicate events, and update tenant
  plan/status.**

```
PROBE 4 — forged webhook -> 400 (nothing changes); replay -> once
forged signature -> 400 (must be 400): bad_signature
first delivery  -> subscription_synced:active
replay delivery -> duplicate_ignored (must be duplicate_ignored)
PROBE 4: PASS
```

Plan/status sync is covered by `test_replayed_event_processed_once`,
`test_full_checkout_flow_flips_plan`, `test_subscription_deleted_downgrades`.

## Data model, tests & documentation

- [x] **Database includes tenants, plans, subscriptions, and usage events;
  customer data isolated per tenant** — every usage/webhook row carries
  `tenant_id`; all queries filter by it; `api_key` is unique per tenant
  (`app/migrations/001_init.sql`, `app/models.py`).

- [x] **README + architecture diagram + setup instructions; all Section 10
  required files present**: `README.md`, `DESIGN.md`, `capstone.yaml`,
  `EVIDENCE.md` (this file), `BUILDLOG.md`, `.env.example`.
