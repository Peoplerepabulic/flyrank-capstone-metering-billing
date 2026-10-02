"""SQLAlchemy models mirroring migrations/001_init.sql."""
from __future__ import annotations

from sqlalchemy import (Column, DateTime, ForeignKey, Integer, String, Text,
                        UniqueConstraint, func)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Plan(Base):
    __tablename__ = "plans"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    api_calls_quota = Column(Integer, nullable=False)
    ai_tokens_quota = Column(Integer, nullable=False)
    monthly_price_cents = Column(Integer, nullable=False)


class Tenant(Base):
    __tablename__ = "tenants"
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    api_key = Column(String, nullable=False, unique=True)
    plan_id = Column(String, ForeignKey("plans.id"), nullable=False)
    subscription_status = Column(String, nullable=False, default="active")
    created_at = Column(DateTime, server_default=func.now())


class Subscription(Base):
    __tablename__ = "subscriptions"
    id = Column(String, primary_key=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False)
    provider = Column(String, nullable=False)
    provider_subscription_id = Column(String)
    provider_customer_id = Column(String)
    status = Column(String, nullable=False)
    plan_id = Column(String, ForeignKey("plans.id"), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class UsageEvent(Base):
    __tablename__ = "usage_events"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String, ForeignKey("tenants.id"), nullable=False)
    period = Column(String, nullable=False)
    idempotency_key = Column(String, nullable=False)
    api_calls = Column(Integer, nullable=False, default=0)
    input_tokens = Column(Integer, nullable=False, default=0)
    cached_input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    reasoning_tokens = Column(Integer, nullable=False, default=0)
    cost_microdollars = Column(Integer, nullable=False)
    response_json = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String, nullable=False)
    provider_event_id = Column(String, nullable=False, unique=True)
    event_type = Column(String, nullable=False)
    payload_json = Column(Text, nullable=False)
    processed_at = Column(DateTime, server_default=func.now())
    result = Column(String, nullable=False)


class Alert(Base):
    __tablename__ = "alerts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    kind = Column(String, nullable=False)
    message = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
