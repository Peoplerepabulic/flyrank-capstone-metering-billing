"""Simulated billing provider: behaves like Stripe test mode with $0 and no account.

Used when BILLING_PROVIDER=simulated (the default). Webhooks are HMAC-signed with
SIM_WEBHOOK_SECRET and delivered to the SAME /v1/webhooks/billing endpoint as real
Stripe events, so signature verification, dedup, and plan-sync code is genuinely
exercised. This is the documented $0 path (see README "Limitations").
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid

from .base import (BillingProvider, CheckoutSession, WebhookEvent,
                   WebhookVerificationError)


def _secret() -> str:
    return os.environ.get("SIM_WEBHOOK_SECRET", "dev-only-sim-secret")


def sign_event(event_id: str, event_type: str, payload: dict) -> str:
    body = json.dumps({"id": event_id, "type": event_type, "data": payload},
                      sort_keys=True).encode()
    return hmac.new(_secret().encode(), body, hashlib.sha256).hexdigest()


def build_event(event_type: str, payload: dict, event_id: str | None = None) -> tuple[bytes, str]:
    """Build a signed simulated webhook body. Returns (raw_body, signature)."""
    event_id = event_id or f"evt_sim_{uuid.uuid4().hex[:16]}"
    raw = json.dumps({"id": event_id, "type": event_type, "data": payload},
                     sort_keys=True).encode()
    sig = hmac.new(_secret().encode(), raw, hashlib.sha256).hexdigest()
    return raw, sig


class SimulatedProvider(BillingProvider):
    name = "simulated"
    # In-memory checkout sessions (test-mode equivalent; nothing persists).
    _sessions: dict[str, dict] = {}

    def create_checkout(self, tenant_id: str, tenant_name: str, plan_id: str,
                        success_url: str, cancel_url: str) -> CheckoutSession:
        session_id = f"cs_sim_{uuid.uuid4().hex[:16]}"
        self._sessions[session_id] = {
            "tenant_id": tenant_id, "plan_id": plan_id,
            "created": int(time.time()),
        }
        # In real Stripe this would be a stripe.com URL. Here the "customer"
        # confirms via POST /v1/billing/simulate/complete, which fires the
        # same webhook flow a real Checkout would.
        return CheckoutSession(
            provider=self.name,
            session_id=session_id,
            url=f"/v1/billing/simulate/complete?session_id={session_id}",
            plan_id=plan_id,
            tenant_id=tenant_id,
        )

    def verify_webhook(self, raw_body: bytes, signature: str | None) -> WebhookEvent:
        if not signature:
            raise WebhookVerificationError("missing webhook signature")
        expected = hmac.new(_secret().encode(), raw_body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise WebhookVerificationError("webhook signature mismatch")
        try:
            data = json.loads(raw_body)
            return WebhookEvent(provider=self.name, event_id=data["id"],
                                event_type=data["type"], payload=data["data"])
        except (KeyError, ValueError, TypeError) as e:
            raise WebhookVerificationError(f"malformed webhook body: {e}")
