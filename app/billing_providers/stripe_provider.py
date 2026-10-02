"""Real Stripe provider (test mode only). Enabled when STRIPE_SECRET_KEY is set.

Never use live mode with this service. Test cards like 4242 4242 4242 4242 work
with any future expiry. Use the Stripe CLI to forward webhooks locally:
    stripe listen --forward-to localhost:8000/v1/webhooks/billing
"""
from __future__ import annotations

import os

import stripe

from .base import (BillingProvider, CheckoutSession, WebhookEvent,
                   WebhookVerificationError)


class StripeProvider(BillingProvider):
    name = "stripe"

    def __init__(self):
        self.api_key = os.environ["STRIPE_SECRET_KEY"]
        self.webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
        stripe.api_key = self.api_key
        if self.api_key.startswith("sk_live"):
            raise RuntimeError("live Stripe keys are forbidden: test mode only")

    def create_checkout(self, tenant_id: str, tenant_name: str, plan_id: str,
                        success_url: str, cancel_url: str) -> CheckoutSession:
        # Prices are created in the Stripe test dashboard; map plan -> price id.
        price_id = os.environ.get(f"STRIPE_PRICE_{plan_id.upper()}")
        if not price_id:
            raise RuntimeError(
                f"STRIPE_PRICE_{plan_id.upper()} is not set: create a recurring "
                "test-mode price in the Stripe dashboard and export its id.")
        session = stripe.checkout.Session.create(
            mode="subscription",
            customer_email=None,
            client_reference_id=tenant_id,
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={"tenant_id": tenant_id, "plan_id": plan_id},
        )
        return CheckoutSession(provider=self.name, session_id=session.id,
                               url=session.url, plan_id=plan_id, tenant_id=tenant_id)

    def verify_webhook(self, raw_body: bytes, signature: str | None) -> WebhookEvent:
        if not signature or not self.webhook_secret:
            raise WebhookVerificationError("missing webhook signature or secret")
        try:
            event = stripe.Webhook.construct_event(raw_body, signature, self.webhook_secret)
        except stripe.error.SignatureVerificationError as e:
            raise WebhookVerificationError(f"stripe signature invalid: {e}")
        except Exception as e:  # malformed payload
            raise WebhookVerificationError(f"malformed stripe webhook: {e}")
        return WebhookEvent(provider=self.name, event_id=event["id"],
                            event_type=event["type"], payload=event["data"]["object"])
