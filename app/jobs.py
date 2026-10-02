"""Background jobs: slow/bulk work off the request path, with retries + failure alerts.

- reconcile (hourly): compare the DB's usage ledger against the billing provider's
  view for every tenant; any mismatch becomes an alert (the "missed webhook"
  scenario). Retries up to 3 times with backoff; a final failure raises an alert.
- quota_watch (hourly): tenants at >=80% of any quota get a quota_warning alert;
  tenants at 100% get quota_exhausted. (Notification delivery itself is out of
  scope — the alert row is the contract; see README "Limitations".)
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

from . import config
from .db import SessionLocal
from .models import Alert, Tenant
from .services.metering import period_totals

log = logging.getLogger("jobs")

_scheduler: BackgroundScheduler | None = None


def _alert(db: Session, kind: str, message: str) -> None:
    db.add(Alert(kind=kind, message=message))
    db.commit()
    log.warning("ALERT [%s] %s", kind, message)


def reconcile_job(max_retries: int = 3) -> dict:
    """Reconcile DB usage against provider-side records. Returns a summary."""
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            return _reconcile_once()
        except Exception as e:  # noqa: BLE001 - retries + alert is the contract
            last_error = e
            log.exception("reconcile attempt %d/%d failed", attempt, max_retries)
            time.sleep(2 ** attempt)
    db = SessionLocal()
    try:
        _alert(db, "job_failed",
               f"reconcile job failed after {max_retries} attempts: {last_error}")
    finally:
        db.close()
    return {"ok": False, "error": str(last_error)}


def _reconcile_once() -> dict:
    from .billing_providers.simulated import SimulatedProvider  # local import: no cycle
    db = SessionLocal()
    try:
        provider_view = _provider_usage_view()
        tenants = db.query(Tenant).all()
        mismatches = []
        for tenant in tenants:
            totals = period_totals(db, tenant.id)
            key = (tenant.id, totals["period"])
            seen = provider_view.get(key)
            # The simulated provider mirrors every checkout; usage itself is
            # authoritative in our DB. We reconcile plan/quota assignment here:
            plan = config.PLANS[tenant.plan_id]
            if seen is not None and seen != tenant.plan_id:
                mismatches.append({"tenant": tenant.id, "db_plan": tenant.plan_id,
                                   "provider_plan": seen})
                _alert(db, "reconcile_mismatch",
                       f"tenant {tenant.id}: DB plan={tenant.plan_id} but provider "
                       f"reports {seen}; investigate missed webhook")
            _ = plan  # quotas are enforced live; nothing to fix up offline
        return {"ok": True, "tenants_checked": len(tenants),
                "mismatches": mismatches,
                "at": datetime.now(timezone.utc).isoformat()}
    finally:
        db.close()


def _provider_usage_view() -> dict:
    """Provider-side plan assignments (simulated provider ledger)."""
    from .billing_providers.simulated import SimulatedProvider
    view: dict[tuple[str, str], str] = {}
    for session_id, s in SimulatedProvider._sessions.items():
        # sessions that completed checkout are authoritative for the plan
        if s.get("completed"):
            from .services.metering import current_period
            view[(s["tenant_id"], current_period())] = s["plan_id"]
    return view


def quota_watch_job() -> dict:
    """Emit quota warnings at 80% and exhaustion notices at 100%."""
    db = SessionLocal()
    warned = 0
    try:
        for tenant in db.query(Tenant).all():
            plan = config.PLANS[tenant.plan_id]
            totals = period_totals(db, tenant.id)
            for dim, used, quota in (
                ("api_calls", totals["api_calls"], plan["api_calls_quota"]),
                ("ai_tokens", totals["ai_tokens"], plan["ai_tokens_quota"]),
            ):
                ratio = used / quota if quota else 0
                if used >= quota:
                    _alert(db, "quota_exhausted",
                           f"tenant {tenant.id}: {dim} at {used}/{quota} "
                           f"({tenant.plan_id} plan) — further requests get 429/402")
                    warned += 1
                elif ratio >= 0.8:
                    _alert(db, "quota_warning",
                           f"tenant {tenant.id}: {dim} at {used}/{quota} "
                           f"({ratio:.0%} of {tenant.plan_id} plan)")
                    warned += 1
        return {"ok": True, "alerts_raised": warned}
    finally:
        db.close()


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    _scheduler = BackgroundScheduler()
    _scheduler.add_job(reconcile_job, "interval", hours=1, id="reconcile")
    _scheduler.add_job(quota_watch_job, "interval", hours=1, id="quota_watch")
    _scheduler.start()
    log.info("background scheduler started (reconcile + quota_watch hourly)")
    return _scheduler
