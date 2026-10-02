"""Apply signature-verified billing webhooks to the database.

Rules:
- Every event is recorded in webhook_events exactly once (UNIQUE provider_event_id).
  A replayed event returns "duplicate_ignored" and changes nothing.
- checkout.session.completed -> tenant moves to the purchased plan, subscription
  becomes active.
- customer.subscription.updated -> subscription status/plan synced.
- customer.subscription.deleted -> subscription canceled, tenant falls back to Free.
- Payment truth lives at the provider; we only mirror verified events.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..billing_providers.base import WebhookEvent
from ..models import Subscription, Tenant, WebhookEvent as WebhookEventRow


def _tenant_id_from(event: WebhookEvent) -> str | None:
    p = event.payload
    return (p.get("tenant_id")
            or (p.get("metadata") or {}).get("tenant_id")
            or p.get("client_reference_id"))


def _plan_id_from(event: WebhookEvent) -> str | None:
    p = event.payload
    return (p.get("plan_id") or (p.get("metadata") or {}).get("plan_id"))


def apply_webhook(db: Session, event: WebhookEvent) -> str:
    """Apply a verified webhook event. Returns a result string for the audit log."""
    row = WebhookEventRow(
        provider=event.provider,
        provider_event_id=event.event_id,
        event_type=event.event_type,
        payload_json=json.dumps(event.payload, sort_keys=True),
        result="pending",
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return "duplicate_ignored"
    db.refresh(row)

    result = _dispatch(db, event)
    row.result = result
    db.commit()
    return result


def _dispatch(db: Session, event: WebhookEvent) -> str:
    t = event.event_type
    if t == "checkout.session.completed":
        return _checkout_completed(db, event)
    if t == "customer.subscription.updated":
        return _subscription_updated(db, event)
    if t == "customer.subscription.deleted":
        return _subscription_deleted(db, event)
    return f"ignored_unknown_type:{t}"


def _get_tenant(db: Session, tenant_id: str | None) -> Tenant | None:
    if not tenant_id:
        return None
    return db.execute(select(Tenant).where(Tenant.id == tenant_id)).scalar_one_or_none()


def _checkout_completed(db: Session, event: WebhookEvent) -> str:
    tenant = _get_tenant(db, _tenant_id_from(event))
    plan_id = _plan_id_from(event) or "pro"
    if tenant is None:
        return "tenant_not_found"
    payload = event.payload
    sub = Subscription(
        id=f"sub_{uuid.uuid4().hex[:12]}",
        tenant_id=tenant.id,
        provider=event.provider,
        provider_subscription_id=payload.get("subscription_id") or payload.get("subscription"),
        provider_customer_id=payload.get("customer_id") or payload.get("customer"),
        status="active",
        plan_id=plan_id,
    )
    db.add(sub)
    tenant.plan_id = plan_id
    tenant.subscription_status = "active"
    return f"tenant_upgraded_to:{plan_id}"


def _subscription_updated(db: Session, event: WebhookEvent) -> str:
    tenant = _get_tenant(db, _tenant_id_from(event))
    if tenant is None:
        return "tenant_not_found"
    payload = event.payload
    status = payload.get("status", "active")
    plan_id = _plan_id_from(event) or tenant.plan_id
    sub = db.execute(
        select(Subscription)
        .where(Subscription.tenant_id == tenant.id)
        .order_by(Subscription.created_at.desc())
    ).scalars().first()
    if sub is not None:
        sub.status = status
        sub.plan_id = plan_id
        sub.updated_at = datetime.now(timezone.utc)
    tenant.subscription_status = status
    # A past_due subscription keeps its plan but blocks billable actions (402).
    if status == "active":
        tenant.plan_id = plan_id
    return f"subscription_synced:{status}"


def _subscription_deleted(db: Session, event: WebhookEvent) -> str:
    tenant = _get_tenant(db, _tenant_id_from(event))
    if tenant is None:
        return "tenant_not_found"
    sub = db.execute(
        select(Subscription)
        .where(Subscription.tenant_id == tenant.id)
        .order_by(Subscription.created_at.desc())
    ).scalars().first()
    if sub is not None:
        sub.status = "canceled"
        sub.updated_at = datetime.now(timezone.utc)
    tenant.subscription_status = "canceled"
    tenant.plan_id = "free"
    return "subscription_canceled_downgraded_to_free"
