"""Billing provider interface.

Two implementations:
- simulated.py: a built-in fake that behaves like Stripe test mode ($0, no account).
- stripe_provider.py: real Stripe SDK in test mode, enabled via STRIPE_SECRET_KEY.

Payment truth lives at the provider; the database mirrors it through
signature-verified webhooks only.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class CheckoutSession:
    provider: str
    session_id: str
    url: str
    plan_id: str
    tenant_id: str


@dataclass
class WebhookEvent:
    provider: str
    event_id: str
    event_type: str
    payload: dict


class BillingProvider(Protocol):
    name: str

    def create_checkout(self, tenant_id: str, tenant_name: str, plan_id: str,
                        success_url: str, cancel_url: str) -> CheckoutSession: ...

    def verify_webhook(self, raw_body: bytes, signature: str | None) -> WebhookEvent:
        """Verify the webhook signature. Raises WebhookVerificationError on failure."""
        ...


class WebhookVerificationError(Exception):
    pass
