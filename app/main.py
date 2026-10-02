"""Usage Metering & Billing Engine — FastAPI app.

One metering path, one read path, one payment-sync path. Small on purpose,
correct by construction.
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import uuid

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .billing_providers.base import BillingProvider, WebhookVerificationError
from .billing_providers.simulated import SimulatedProvider, build_event
from .db import SessionLocal, get_db, run_migrations
from .jobs import quota_watch_job, reconcile_job, start_scheduler
from .models import Plan, Tenant
from .schemas import GenerateRequest, TenantCreate
from .services import stripe_sync
from .services.metering import find_by_idempotency_key, period_totals, record_usage
from .services.quotas import (PaymentRequired, QuotaExceeded, check_quotas,
                              payment_message, quota_message)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("app")

app = FastAPI(title="Usage Metering & Billing Engine",
              version="1.0.0")


# ---------------------------------------------------------------- startup
def get_provider() -> BillingProvider:
    choice = os.environ.get("BILLING_PROVIDER", "simulated").lower()
    if choice == "stripe" and os.environ.get("STRIPE_SECRET_KEY"):
        from .billing_providers.stripe_provider import StripeProvider
        return StripeProvider()
    if choice == "stripe":
        log.warning("BILLING_PROVIDER=stripe but STRIPE_SECRET_KEY is unset; "
                    "falling back to the simulated provider")
    return SimulatedProvider()


PROVIDER: BillingProvider = get_provider()


@app.on_event("startup")
def _startup():
    run_migrations()
    db = SessionLocal()
    try:
        for pid, p in config.PLANS.items():
            if db.get(Plan, pid) is None:
                db.add(Plan(id=pid, name=p["name"],
                            api_calls_quota=p["api_calls_quota"],
                            ai_tokens_quota=p["ai_tokens_quota"],
                            monthly_price_cents=p["monthly_price_cents"]))
        db.commit()
    finally:
        db.close()
    start_scheduler()
    log.info("ready: billing provider=%s", PROVIDER.name)


# ---------------------------------------------------------------- helpers
def _err(status: int, error: str, message: str, hint: str | None = None):
    body = {"error": error, "message": message}
    if hint:
        body["hint"] = hint
    return JSONResponse(status_code=status, content=body)


def _tenant_or_401(db: Session, tenant_key: str | None) -> Tenant | JSONResponse:
    if not tenant_key:
        return _err(401, "unauthorized", "Missing X-Tenant-Key header.",
                    "Create a tenant via POST /admin/tenants, then pass its api_key.")
    tenant = db.execute(select(Tenant).where(Tenant.api_key == tenant_key)).scalar_one_or_none()
    if tenant is None:
        return _err(401, "unauthorized", "Unknown tenant key.")
    return tenant


@app.exception_handler(Exception)
async def _never_500_leak(request: Request, exc: Exception):
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return _err(500, "internal_error",
                "Something went wrong on our side. The request was not billed.")


# ---------------------------------------------------------------- health
@app.get("/health")
def health():
    return {"ok": True, "provider": PROVIDER.name}


@app.get("/v1/plans")
def list_plans():
    return {"plans": [
        {"id": pid, **{k: v for k, v in p.items()}}
        for pid, p in config.PLANS.items()
    ]}


# ---------------------------------------------------------------- metering
@app.post("/v1/generate")
def generate(
    body: GenerateRequest,
    db: Session = Depends(get_db),
    x_tenant_key: str | None = Header(None, alias="X-Tenant-Key"),
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
):
    tenant = _tenant_or_401(db, x_tenant_key)
    if isinstance(tenant, JSONResponse):
        return tenant
    if not idempotency_key:
        return _err(400, "missing_idempotency_key",
                    "The Idempotency-Key header is required on billable endpoints.",
                    "Send a UUIDv4 per logical request; retries reuse the same key.")

    # Exactly-once: a replayed key returns the ORIGINAL response verbatim.
    replay = find_by_idempotency_key(db, tenant.id, idempotency_key)
    if replay is not None:
        return JSONResponse(status_code=200, content={
            **json.loads(replay.response_json), "replayed": True,
            "idempotency_key": idempotency_key})

    requested_tokens = (body.input_tokens + body.cached_input_tokens
                        + body.output_tokens + body.reasoning_tokens)
    plan = config.PLANS[tenant.plan_id]
    try:
        check_quotas(db, tenant, config.PLANS[tenant.plan_id],
                     requested_api_calls=1, requested_ai_tokens=requested_tokens)
    except PaymentRequired as e:
        return _err(402, "payment_required", payment_message(e),
                    "Resolve billing, then retry with the same Idempotency-Key.")
    except QuotaExceeded as e:
        return _err(429, "quota_exceeded", quota_message(e))

    response_payload = {
        "ok": True,
        "tenant_id": tenant.id,
        "idempotency_key": idempotency_key,
        "billed": {
            "api_calls": 1,
            "input_tokens": body.input_tokens,
            "cached_input_tokens": body.cached_input_tokens,
            "output_tokens": body.output_tokens,
            "reasoning_tokens": body.reasoning_tokens,
        },
    }
    event, created = record_usage(
        db, tenant.id, idempotency_key,
        api_calls=1,
        input_tokens=body.input_tokens,
        cached_input_tokens=body.cached_input_tokens,
        output_tokens=body.output_tokens,
        reasoning_tokens=body.reasoning_tokens,
        response_payload=response_payload,
    )
    if not created:
        # Lost a race with a concurrent retry: mirror the winner.
        return JSONResponse(status_code=200, content={
            **json.loads(event.response_json), "replayed": True,
            "idempotency_key": idempotency_key})
    totals = period_totals(db, tenant.id)
    response_payload["usage"] = {
        "period": totals["period"],
        "api_calls_used": totals["api_calls"],
        "ai_tokens_used": totals["ai_tokens"],
        "cost_microdollars": totals["cost_microdollars"],
        "cost_display": config.ud_to_dollars_str(totals["cost_microdollars"]),
    }
    # Persist the enriched response so replays mirror exactly this.
    event.response_json = json.dumps(response_payload)
    db.commit()
    return JSONResponse(status_code=200, content=response_payload)


@app.get("/v1/usage")
def usage(db: Session = Depends(get_db),
          x_tenant_key: str | None = Header(None, alias="X-Tenant-Key")):
    tenant = _tenant_or_401(db, x_tenant_key)
    if isinstance(tenant, JSONResponse):
        return tenant
    plan = config.PLANS[tenant.plan_id]
    totals = period_totals(db, tenant.id)
    return {
        "tenant_id": tenant.id,
        "plan_id": tenant.plan_id,
        "subscription_status": tenant.subscription_status,
        "period": totals["period"],
        "api_calls": {"used": totals["api_calls"], "quota": plan["api_calls_quota"],
                      "remaining": max(0, plan["api_calls_quota"] - totals["api_calls"])},
        "ai_tokens": {"used": totals["ai_tokens"], "quota": plan["ai_tokens_quota"],
                      "remaining": max(0, plan["ai_tokens_quota"] - totals["ai_tokens"])},
        "cost": {"microdollars": totals["cost_microdollars"],
                 "display": config.ud_to_dollars_str(totals["cost_microdollars"])},
        "pricing": {
            "input_per_1M": "$1.50", "cached_input_per_1M": "$0.75",
            "output_per_1M": "$6.00",
            "note": "reasoning tokens are billed at the output rate",
        },
    }


# ---------------------------------------------------------------- billing
@app.post("/v1/billing/checkout")
def create_checkout(plan_id: str = "pro",
                    db: Session = Depends(get_db),
                    x_tenant_key: str | None = Header(None, alias="X-Tenant-Key")):
    tenant = _tenant_or_401(db, x_tenant_key)
    if isinstance(tenant, JSONResponse):
        return tenant
    if plan_id not in config.PLANS:
        return _err(400, "unknown_plan", f"Unknown plan '{plan_id}'.",
                    f"Choose from: {', '.join(config.PLANS)}")
    session = PROVIDER.create_checkout(
        tenant_id=tenant.id, tenant_name=tenant.name, plan_id=plan_id,
        success_url="http://localhost:8000/v1/billing/success",
        cancel_url="http://localhost:8000/v1/billing/cancel")
    return {"provider": session.provider, "session_id": session.session_id,
            "checkout_url": session.url, "plan_id": session.plan_id}


@app.post("/v1/billing/simulate/complete")
def simulate_complete(session_id: str, db: Session = Depends(get_db)):
    """Dev-only: confirm a simulated checkout, firing the real webhook flow.

    Disabled unless the simulated provider is active. In production Stripe this
    step is the customer paying on stripe.com; here we emulate it so the
    signature-verification + dedup + plan-sync path is genuinely exercised.
    """
    if PROVIDER.name != "simulated":
        return _err(404, "not_found", "Simulated checkout is only available "
                                      "with BILLING_PROVIDER=simulated.")
    provider = PROVIDER
    assert isinstance(provider, SimulatedProvider)
    sess = provider._sessions.get(session_id)
    if sess is None:
        return _err(404, "unknown_session", f"No checkout session '{session_id}'.")
    if sess.get("completed"):
        return {"ok": True, "already_completed": True}
    sess["completed"] = True
    raw, sig = build_event("checkout.session.completed", {
        "tenant_id": sess["tenant_id"],
        "plan_id": sess["plan_id"],
        "session_id": session_id,
        "subscription_id": f"sub_sim_{uuid.uuid4().hex[:12]}",
        "customer_id": f"cus_sim_{uuid.uuid4().hex[:12]}",
    })
    event = provider.verify_webhook(raw, sig)
    result = stripe_sync.apply_webhook(db, event)
    return {"ok": True, "webhook_result": result, "tenant_id": sess["tenant_id"]}


@app.post("/v1/webhooks/billing")
async def billing_webhook(request: Request, db: Session = Depends(get_db)):
    raw = await request.body()
    signature = request.headers.get("X-Webhook-Signature") or \
        request.headers.get("Stripe-Signature")
    try:
        event = PROVIDER.verify_webhook(raw, signature)
    except WebhookVerificationError as e:
        return _err(400, "bad_signature",
                    f"Webhook signature verification failed: {e}. Nothing was changed.")
    result = stripe_sync.apply_webhook(db, event)
    return {"ok": True, "provider": event.provider, "event_id": event.event_id,
            "type": event.event_type, "result": result}


# ---------------------------------------------------------------- admin
@app.post("/admin/tenants")
def create_tenant(body: TenantCreate, db: Session = Depends(get_db)):
    tenant = Tenant(id=f"tnt_{uuid.uuid4().hex[:12]}", name=body.name,
                    api_key=f"key_{secrets.token_urlsafe(24)}",
                    plan_id=body.plan_id, subscription_status="active")
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    return {"id": tenant.id, "name": tenant.name, "api_key": tenant.api_key,
            "plan_id": tenant.plan_id}


@app.post("/admin/jobs/reconcile")
def run_reconcile():
    return reconcile_job()


@app.post("/admin/jobs/quota-watch")
def run_quota_watch():
    return quota_watch_job()


@app.get("/admin/alerts")
def list_alerts(db: Session = Depends(get_db), limit: int = 50):
    from .models import Alert
    rows = db.query(Alert).order_by(Alert.id.desc()).limit(limit).all()
    return {"alerts": [{"id": a.id, "kind": a.kind, "message": a.message,
                        "created_at": str(a.created_at)} for a in rows]}
