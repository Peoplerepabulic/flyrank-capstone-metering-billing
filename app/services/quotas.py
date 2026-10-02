"""Quota enforcement: honest API boundaries.

Documented rule: a billable action is allowed iff
    current_period_usage + requested <= plan_limit.
A request landing exactly on the limit succeeds; the next one over it fails.

- 429 Too Many Requests: quota exhausted while the subscription is in good
  standing. The message names the limit and hints at upgrading.
- 402 Payment Required: the subscription is past_due/canceled — no billable
  action is allowed until payment is sorted, regardless of remaining quota.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from .. import config
from ..models import Plan, Tenant
from .metering import period_totals


class QuotaExceeded(Exception):
    def __init__(self, dimension: str, used: int, requested: int, limit: int, plan_id: str):
        self.dimension = dimension
        self.used = used
        self.requested = requested
        self.limit = limit
        self.plan_id = plan_id
        super().__init__(
            f"{dimension} quota exceeded: used {used} + requested {requested} "
            f"would pass the {plan_id} plan limit of {limit}."
        )


class PaymentRequired(Exception):
    def __init__(self, status: str):
        self.status = status
        super().__init__(
            f"Subscription status is '{status}'. Billable actions are blocked "
            "until payment is resolved."
        )


@dataclass
class QuotaCheck:
    allowed: bool
    api_calls_used: int
    ai_tokens_used: int


def check_quotas(db: Session, tenant: Tenant, plan: dict,
                 requested_api_calls: int, requested_ai_tokens: int) -> QuotaCheck:
    """Raise PaymentRequired / QuotaExceeded, or return the current usage.

    `plan` is a config.PLANS entry (dict with api_calls_quota / ai_tokens_quota).
    """
    if tenant.subscription_status in ("past_due", "canceled", "unpaid"):
        raise PaymentRequired(tenant.subscription_status)

    totals = period_totals(db, tenant.id)
    used_calls = totals["api_calls"]
    used_tokens = totals["ai_tokens"]
    plan_id = tenant.plan_id

    if used_calls + requested_api_calls > plan["api_calls_quota"]:
        raise QuotaExceeded("api_calls", used_calls, requested_api_calls,
                            plan["api_calls_quota"], plan_id)
    if used_tokens + requested_ai_tokens > plan["ai_tokens_quota"]:
        raise QuotaExceeded("ai_tokens", used_tokens, requested_ai_tokens,
                            plan["ai_tokens_quota"], plan_id)
    return QuotaCheck(allowed=True, api_calls_used=used_calls, ai_tokens_used=used_tokens)


def quota_message(exc: QuotaExceeded) -> str:
    return (
        f"{exc.dimension} quota exceeded on the '{exc.plan_id}' plan: "
        f"already used {exc.used}, this request needs {exc.requested}, "
        f"limit is {exc.limit} per month. "
        f"Upgrade to Pro for higher limits or wait for the next billing period."
    )


def payment_message(exc: PaymentRequired) -> str:
    return (
        f"Payment required: your subscription status is '{exc.status}', so billable "
        "actions are paused. Update your payment method or contact support to resume."
    )


def get_plan_or_raise(plan_id: str) -> dict:
    try:
        return config.PLANS[plan_id]
    except KeyError:
        raise ValueError(f"unknown plan '{plan_id}'")
