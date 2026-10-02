"""Pydantic schemas: validation at the boundary. Bad input -> clean 4xx, never 500."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator


class GenerateRequest(BaseModel):
    input_tokens: int = Field(0, ge=0, le=10_000_000)
    cached_input_tokens: int = Field(0, ge=0, le=10_000_000)
    output_tokens: int = Field(0, ge=0, le=10_000_000)
    reasoning_tokens: int = Field(0, ge=0, le=10_000_000)

    @field_validator("*")
    @classmethod
    def _ints(cls, v):
        if not isinstance(v, int):
            raise ValueError("token counts must be integers")
        return v


class TenantCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    plan_id: str = Field("free", pattern="^(free|pro)$")


class UsageSummary(BaseModel):
    tenant_id: str
    plan_id: str
    period: str
    api_calls_used: int
    api_calls_quota: int
    ai_tokens_used: int
    ai_tokens_quota: int
    cost_microdollars: int
    cost_display: str


class ErrorBody(BaseModel):
    error: str
    message: str
    hint: Optional[str] = None
