"""Webhooks: bad signature -> 400 + nothing changes; replay -> processed once;
checkout.completed -> tenant flips Free -> Pro."""
import json

from app.billing_providers.simulated import build_event
from tests.conftest import auth_headers


def _usage(client, tenant):
    return client.get("/v1/usage",
                      headers={"X-Tenant-Key": tenant["api_key"]}).json()


def test_forged_webhook_rejected(client, tenant):
    before = _usage(client, tenant)["plan_id"]
    raw, _sig = build_event("checkout.session.completed",
                            {"tenant_id": tenant["id"], "plan_id": "pro"})
    r = client.post("/v1/webhooks/billing", content=raw,
                    headers={"X-Webhook-Signature": "forged-bad-signature",
                             "Content-Type": "application/json"})
    assert r.status_code == 400, r.text
    assert r.json()["error"] == "bad_signature"
    assert _usage(client, tenant)["plan_id"] == before  # nothing changed


def test_replayed_event_processed_once(client, tenant):
    raw, sig = build_event("checkout.session.completed",
                           {"tenant_id": tenant["id"], "plan_id": "pro"})
    headers = {"X-Webhook-Signature": sig, "Content-Type": "application/json"}
    r1 = client.post("/v1/webhooks/billing", content=raw, headers=headers)
    r2 = client.post("/v1/webhooks/billing", content=raw, headers=headers)
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["result"] == "tenant_upgraded_to:pro"
    assert r2.json()["result"] == "duplicate_ignored"
    assert _usage(client, tenant)["plan_id"] == "pro"


def test_full_checkout_flow_flips_plan(client, tenant):
    assert _usage(client, tenant)["plan_id"] == "free"
    r = client.post("/v1/billing/checkout?plan_id=pro",
                    headers={"X-Tenant-Key": tenant["api_key"]})
    assert r.status_code == 200, r.text
    session_id = r.json()["session_id"]
    r = client.post(f"/v1/billing/simulate/complete?session_id={session_id}")
    assert r.status_code == 200, r.text
    assert r.json()["webhook_result"] == "tenant_upgraded_to:pro"
    after = _usage(client, tenant)
    assert after["plan_id"] == "pro"
    assert after["ai_tokens"]["quota"] == 10_000_000  # new limits visible


def test_subscription_deleted_downgrades(client, tenant):
    raw, sig = build_event("customer.subscription.deleted",
                           {"tenant_id": tenant["id"]})
    r = client.post("/v1/webhooks/billing", content=raw,
                    headers={"X-Webhook-Signature": sig,
                             "Content-Type": "application/json"})
    assert r.status_code == 200
    assert r.json()["result"] == "subscription_canceled_downgraded_to_free"
    after = _usage(client, tenant)
    assert after["plan_id"] == "free"
    assert after["subscription_status"] == "canceled"
    # Billable actions now blocked with 402, not 429.
    r = client.post("/v1/generate", json={},
                    headers=auth_headers(tenant, "after-cancel"))
    assert r.status_code == 402, r.text
    assert r.json()["error"] == "payment_required"
