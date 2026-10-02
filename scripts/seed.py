"""Seed demo data: two tenants (one Free, one Pro) for reviewers to probe."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import SessionLocal, run_migrations  # noqa: E402
from app.models import Plan, Tenant  # noqa: E402
from app import config  # noqa: E402

run_migrations()
db = SessionLocal()
try:
    for pid, p in config.PLANS.items():
        if db.get(Plan, pid) is None:
            db.add(Plan(id=pid, name=p["name"], api_calls_quota=p["api_calls_quota"],
                        ai_tokens_quota=p["ai_tokens_quota"],
                        monthly_price_cents=p["monthly_price_cents"]))
    demo = [
        ("tnt_demo_free", "Demo Free Tenant", "demo-key-123", "free"),
        ("tnt_demo_pro", "Demo Pro Tenant", "demo-key-456", "pro"),
    ]
    for tid, name, key, plan in demo:
        if db.get(Tenant, tid) is None:
            db.add(Tenant(id=tid, name=name, api_key=key, plan_id=plan,
                          subscription_status="active"))
            print(f"created tenant {tid} key={key} plan={plan}")
        else:
            print(f"tenant {tid} already exists")
    db.commit()
finally:
    db.close()
print("seed done")
