"""Usage metering: exactly-once recording of billable actions.

Contract: the same request + the same idempotency key = exactly one usage event.
Retries must never create duplicate charges. The UNIQUE(tenant_id, idempotency_key)
constraint is the backstop; the pre-check returns the stored response so a replay
mirrors the original instead of erroring.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import config
from .models import UsageEvent


def current_period(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return now.strftime("%Y-%m")


def find_by_idempotency_key(db: Session, tenant_id: str, idempotency_key: str) -> UsageEvent | None:
    return db.execute(
        select(UsageEvent).where(
            UsageEvent.tenant_id == tenant_id,
            UsageEvent.idempotency_key == idempotency_key,
        )
    ).scalar_one_or_none()


def record_usage(db: Session, tenant_id: str, idempotency_key: str,
                 api_calls: int, input_tokens: int, cached_input_tokens: int,
                 output_tokens: int, reasoning_tokens: int,
                 response_payload: dict) -> tuple[UsageEvent, bool]:
    """Record one billable action. Returns (event, created).

    If the idempotency key was seen before, returns the original event and
    created=False — the caller must return the stored response verbatim.
    """
    existing = find_by_idempotency_key(db, tenant_id, idempotency_key)
    if existing is not None:
        return existing, False

    cost_ud = config.total_cost_ud(
        input_tokens, cached_input_tokens, output_tokens, reasoning_tokens, api_calls
    )
    event = UsageEvent(
        tenant_id=tenant_id,
        period=current_period(),
        idempotency_key=idempotency_key,
        api_calls=api_calls,
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        output_tokens=output_tokens,
        reasoning_tokens=reasoning_tokens,
        cost_microdollars=cost_ud,
        response_json=json.dumps(response_payload),
    )
    db.add(event)
    try:
        db.commit()
    except IntegrityError:
        # Lost a race with a concurrent retry: the other insert won.
        # Roll back and return the winner — still exactly one event.
        db.rollback()
        existing = find_by_idempotency_key(db, tenant_id, idempotency_key)
        assert existing is not None
        return existing, False
    db.refresh(event)
    return event, True


def period_totals(db: Session, tenant_id: str, period: str | None = None) -> dict:
    """Summed usage + cost for a tenant in a period (defaults to current month)."""
    period = period or current_period()
    row = db.execute(
        select(
            func.coalesce(func.sum(UsageEvent.api_calls), 0),
            func.coalesce(func.sum(UsageEvent.input_tokens), 0),
            func.coalesce(func.sum(UsageEvent.cached_input_tokens), 0),
            func.coalesce(func.sum(UsageEvent.output_tokens), 0),
            func.coalesce(func.sum(UsageEvent.reasoning_tokens), 0),
            func.coalesce(func.sum(UsageEvent.cost_microdollars), 0),
            func.count(UsageEvent.id),
        ).where(UsageEvent.tenant_id == tenant_id, UsageEvent.period == period)
    ).one()
    api_calls, inp, cached, out, reasoning, cost_ud, events = row
    return {
        "period": period,
        "api_calls": int(api_calls),
        "input_tokens": int(inp),
        "cached_input_tokens": int(cached),
        "output_tokens": int(out),
        "reasoning_tokens": int(reasoning),
        "ai_tokens": int(inp + cached + out + reasoning),
        "cost_microdollars": int(cost_ud),
        "events": int(events),
    }
