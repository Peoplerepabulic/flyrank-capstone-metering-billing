"""Money math: integer-only, categories priced separately, never summed first."""
from app import config


def test_cached_input_is_cheaper_than_regular_input():
    a = config.token_cost_ud(1_000_000, 0, 0, 0)
    b = config.token_cost_ud(0, 1_000_000, 0, 0)
    assert a == 1_500_000  # $1.50
    assert b == 750_000    # $0.75
    assert b < a


def test_reasoning_counts_as_output():
    # 100k reasoning + 0 output must cost exactly like 100k output + 0 reasoning.
    r = config.token_cost_ud(0, 0, 0, 100_000)
    o = config.token_cost_ud(0, 0, 100_000, 0)
    assert r == o == 600_000  # $0.60


def test_categories_priced_separately_not_summed():
    # 1M input + 1M cached + 1M output + 1M reasoning:
    # 1.50 + 0.75 + 6.00 + 6.00 = $14.25 — NOT 4M tokens at any single rate.
    total = config.token_cost_ud(1_000_000, 1_000_000, 1_000_000, 1_000_000)
    assert total == 14_250_000
    assert config.ud_to_cents(total) == 1425
    assert config.ud_to_dollars_str(total) == "$14.25"


def test_evidence_probe5_numbers():
    # The exact figures EVIDENCE.md quotes for PROBE 5.
    total = config.total_cost_ud(
        input_tokens=1_000_000, cached_input_tokens=500_000,
        output_tokens=200_000, reasoning_tokens=100_000, api_calls=10)
    # 1.5 + 0.375 + (0.2+0.1)*6.0 = 3.675 ; calls 10*0.0005 = 0.005 -> $3.68
    assert total == 3_680_000
    assert config.ud_to_dollars_str(total) == "$3.68"


def test_no_floats_anywhere():
    total = config.total_cost_ud(123, 456, 789, 101, 7)
    assert isinstance(total, int)
