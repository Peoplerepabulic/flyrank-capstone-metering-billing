"""Pinned pricing constants and plan definitions.

Money is stored as integer MICRODOLLARS (1e-6 USD) everywhere in the database.
Display values round half-up to cents. These constants are the single source of
truth for every cost figure the API returns; EVIDENCE.md proves the totals.
"""
from __future__ import annotations

# --- Token pricing: exact integer microdollars per 1,000,000 tokens -------------
PRICE_INPUT_PER_MTOKEN_UD = 1_500_000      # $1.50 / 1M input tokens
PRICE_CACHED_INPUT_PER_MTOKEN_UD = 750_000  # $0.75 / 1M cached input tokens (cheaper)
PRICE_OUTPUT_PER_MTOKEN_UD = 6_000_000      # $6.00 / 1M output tokens
# Reasoning tokens count as OUTPUT tokens (real-world rule), never added separately.
PRICE_API_CALL_UD = 500                    # $0.0005 per API call

TOKENS_PER_M = 1_000_000
MICRODOLLARS_PER_CENT = 10_000


def token_cost_ud(input_tokens: int, cached_input_tokens: int,
                 output_tokens: int, reasoning_tokens: int) -> int:
    """Integer-only token cost in microdollars.

    Categories are priced separately and summed — never summed before pricing.
    Reasoning tokens are billed at the output rate.
    """
    for v in (input_tokens, cached_input_tokens, output_tokens, reasoning_tokens):
        if v < 0:
            raise ValueError("token counts must be non-negative")
    billable_output = output_tokens + reasoning_tokens
    return (
        input_tokens * PRICE_INPUT_PER_MTOKEN_UD
        + cached_input_tokens * PRICE_CACHED_INPUT_PER_MTOKEN_UD
        + billable_output * PRICE_OUTPUT_PER_MTOKEN_UD
    ) // TOKENS_PER_M


def api_call_cost_ud(api_calls: int) -> int:
    if api_calls < 0:
        raise ValueError("api_calls must be non-negative")
    return api_calls * PRICE_API_CALL_UD


def total_cost_ud(input_tokens: int, cached_input_tokens: int, output_tokens: int,
                  reasoning_tokens: int, api_calls: int) -> int:
    return token_cost_ud(input_tokens, cached_input_tokens, output_tokens,
                         reasoning_tokens) + api_call_cost_ud(api_calls)


def ud_to_cents(microdollars: int) -> int:
    """Round half-up from microdollars to integer cents for display."""
    return (microdollars + MICRODOLLARS_PER_CENT // 2) // MICRODOLLARS_PER_CENT


def ud_to_dollars_str(microdollars: int) -> str:
    cents = ud_to_cents(microdollars)
    return f"${cents // 100}.{cents % 100:02d}"


# --- Plans ---------------------------------------------------------------------
# Free: 1,000 API calls / month, 100,000 AI tokens / month, $0.
# Pro:  100,000 API calls / month, 10,000,000 AI tokens / month, $49 / month.
# (Pro numbers are our choice, documented here and in the README.)
PLANS: dict[str, dict] = {
    "free": {
        "name": "Free",
        "api_calls_quota": 1_000,
        "ai_tokens_quota": 100_000,
        "monthly_price_cents": 0,
    },
    "pro": {
        "name": "Pro",
        "api_calls_quota": 100_000,
        "ai_tokens_quota": 10_000_000,
        "monthly_price_cents": 4_900,
    },
}
