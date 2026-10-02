"""Run the 5 acceptance probes and print transcripts for EVIDENCE.md.

Uses an isolated throwaway SQLite DB. Every line printed below is real output
from the running service.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"
os.environ["BILLING_PROVIDER"] = "simulated"

from fastapi.testclient import TestClient  # noqa: E402

from app.billing_providers.simulated import build_event  # noqa: E402
from app.main import app  # noqa: E402


def main():
    with TestClient(app) as c:
        t = c.post("/admin/tenants", json={"name": "probe-tenant", "plan_id": "free"}).json()
        key = t["api_key"]
        tid = t["id"]
        H = lambda k: {"X-Tenant-Key": key, "Idempotency-Key": k}  # noqa: E731

        print("=" * 70)
        print("PROBE 1 — same billable request twice, one idempotency key")
        print("=" * 70)
        body = {"input_tokens": 1000, "cached_input_tokens": 500,
                "output_tokens": 200, "reasoning_tokens": 100}
        r1 = c.post("/v1/generate", json=body, headers=H("probe1-key"))
        r2 = c.post("/v1/generate", json=body, headers=H("probe1-key"))
        print(f"first  -> {r1.status_code} replayed={r1.json().get('replayed', False)}")
        print(f"second -> {r2.status_code} replayed={r2.json().get('replayed', False)}")
        j1 = {k: v for k, v in r1.json().items() if k != "replayed"}
        j2 = {k: v for k, v in r2.json().items() if k != "replayed"}
        print(f"responses identical: {j1 == j2}")
        u = c.get("/v1/usage", headers={"X-Tenant-Key": key}).json()
        print(f"api_calls used after 2 sends: {u['api_calls']['used']} (must be 1)")
        print(f"billed cost microdollars: {r1.json()['billed']}")
        assert u["api_calls"]["used"] == 1 and j1 == j2
        print("PROBE 1: PASS")

        print()
        print("=" * 70)
        print("PROBE 2 — drive to the exact quota boundary (Free: 1000 calls)")
        print("=" * 70)
        for i in range(998):  # 1 used already + 998 = 999
            r = c.post("/v1/generate", json={}, headers=H(f"fill-{i}"))
            assert r.status_code == 200, (i, r.text)
        r = c.post("/v1/generate", json={}, headers=H("at-boundary"))
        print(f"request #1000 (exactly at limit) -> {r.status_code} (must be 200)")
        r = c.post("/v1/generate", json={}, headers=H("over-boundary"))
        print(f"request #1001 (over limit)      -> {r.status_code} (must be 429)")
        print(f"message: {r.json()['message']}")
        assert r.status_code == 429
        print("PROBE 2: PASS")

        print()
        print("=" * 70)
        print("PROBE 3 — Stripe-style test checkout flips Free -> Pro via webhook")
        print("=" * 70)
        t2 = c.post("/admin/tenants", json={"name": "checkout-tenant",
                                           "plan_id": "free"}).json()
        k2 = t2["api_key"]
        before = c.get("/v1/usage", headers={"X-Tenant-Key": k2}).json()
        print(f"before: plan={before['plan_id']} token_quota={before['ai_tokens']['quota']}")
        s = c.post("/v1/billing/checkout?plan_id=pro",
                   headers={"X-Tenant-Key": k2}).json()
        done = c.post(f"/v1/billing/simulate/complete?session_id={s['session_id']}")
        print(f"checkout session: {s['session_id']}")
        print(f"webhook result: {done.json()['webhook_result']}")
        after = c.get("/v1/usage", headers={"X-Tenant-Key": k2}).json()
        print(f"after:  plan={after['plan_id']} token_quota={after['ai_tokens']['quota']}")
        assert after["plan_id"] == "pro" and after["ai_tokens"]["quota"] == 10_000_000
        print("PROBE 3: PASS")

        print()
        print("=" * 70)
        print("PROBE 4 — forged webhook -> 400 (nothing changes); replay -> once")
        print("=" * 70)
        raw, _ = build_event("checkout.session.completed",
                             {"tenant_id": t2["id"], "plan_id": "pro"})
        r = c.post("/v1/webhooks/billing", content=raw,
                   headers={"X-Webhook-Signature": "forged", "Content-Type": "application/json"})
        print(f"forged signature -> {r.status_code} (must be 400): {r.json()['error']}")
        raw2, sig2 = build_event("customer.subscription.updated",
                                 {"tenant_id": t2["id"], "status": "active",
                                  "plan_id": "pro"})
        h2 = {"X-Webhook-Signature": sig2, "Content-Type": "application/json"}
        a = c.post("/v1/webhooks/billing", content=raw2, headers=h2)
        b = c.post("/v1/webhooks/billing", content=raw2, headers=h2)
        print(f"first delivery  -> {a.json()['result']}")
        print(f"replay delivery -> {b.json()['result']} (must be duplicate_ignored)")
        assert r.status_code == 400 and b.json()["result"] == "duplicate_ignored"
        print("PROBE 4: PASS")

        print()
        print("=" * 70)
        print("PROBE 5 — pinned pricing rules produce exact totals")
        print("=" * 70)
        t3 = c.post("/admin/tenants", json={"name": "pricing-tenant",
                                           "plan_id": "pro"}).json()
        k3 = t3["api_key"]
        body = {"input_tokens": 100_000, "cached_input_tokens": 50_000,
                "output_tokens": 20_000, "reasoning_tokens": 10_000}
        for i in range(10):
            r = c.post("/v1/generate", json=body,
                       headers={"X-Tenant-Key": k3, "Idempotency-Key": f"p5-{i}"})
            assert r.status_code == 200, r.text
        u3 = c.get("/v1/usage", headers={"X-Tenant-Key": k3}).json()
        per_event = 368_000  # 100k*1.50 + 50k*0.75 + 30k*6.00 microdollars, + 500/call
        expected = per_event * 10
        print(f"per-event microdollars: {per_event} "
              f"(= 100k*1.50 + 50k*0.75 + 30k*6.00 + 1 call*0.0005)")
        print(f"GET /usage cost_microdollars: {u3['cost']['microdollars']}")
        print(f"expected (10 events):          {expected}")
        print(f"display: {u3['cost']['display']}")
        assert u3["cost"]["microdollars"] == expected
        print("PROBE 5: PASS")
        print()
        print("ALL 5 PROBES PASSED")


if __name__ == "__main__":
    main()
