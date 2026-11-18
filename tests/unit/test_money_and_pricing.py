"""
Unit tests for Money Precision Arithmetic and Deterministic Pricing.
(Baseline Control 51; Precision Money Representation; Strictly NO Float Arithmetic)
"""
import pytest
from decimal import Decimal
from src.backend.domains.pricing.money import (
    Money, CurrencyMismatchError, NegativeQuantityError,
    calculate_tax, calculate_discount, calculate_margin_percent
)
from src.backend.domains.pricing.service import PricingService

def test_money_initialization_and_properties():
    m = Money(1050, "MAD")
    assert m.cents == 1050
    assert m.currency == "MAD"
    assert m.decimal_amount == Decimal("10.50")
    assert str(m) == "MAD 10.50"
    assert m.format() == "MAD 10.50"

def test_money_from_major():
    m1 = Money.from_major("1250.75", "MAD")
    assert m1.cents == 125075

    m2 = Money.from_major(Decimal("99.99"), "USD")
    assert m2.cents == 9999
    assert m2.currency == "USD"

def test_money_zero():
    z = Money.zero("EUR")
    assert z.cents == 0
    assert z.currency == "EUR"

def test_money_addition_and_subtraction():
    m1 = Money(5000, "MAD")
    m2 = Money(2500, "MAD")

    sum_m = m1 + m2
    assert sum_m.cents == 7500
    assert sum_m.currency == "MAD"

    diff_m = m1 - m2
    assert diff_m.cents == 2500
    assert diff_m.currency == "MAD"

def test_money_currency_mismatch_rejected():
    m_mad = Money(1000, "MAD")
    m_usd = Money(1000, "USD")

    with pytest.raises(CurrencyMismatchError):
        _ = m_mad + m_usd

    with pytest.raises(CurrencyMismatchError):
        _ = m_mad - m_usd

    with pytest.raises(CurrencyMismatchError):
        _ = m_mad < m_usd

def test_money_multiplication_precision():
    m = Money(1000, "MAD")  # 10.00 MAD
    # Quantity 3
    res = m * 3
    assert res.cents == 3000

    # Decimal factor
    res_dec = m * Decimal("1.5")
    assert res_dec.cents == 1500

    # Reverse multiplication
    res_r = 4 * m
    assert res_r.cents == 4000

def test_money_strictly_forbids_float_multiplication():
    m = Money(1000, "MAD")
    with pytest.raises(TypeError, match="Floating point multiplication is strictly forbidden"):
        _ = m * 1.5

def test_money_percentage_calculation():
    m = Money(10000, "MAD")  # 100.00 MAD
    # 20% TVA
    tax = m.percentage(Decimal("20.00"))
    assert tax.cents == 2000

    # 15.5% discount
    disc = m.percentage("15.5")
    assert disc.cents == 1550

def test_money_comparisons():
    m1 = Money(1000, "MAD")
    m2 = Money(2000, "MAD")
    m3 = Money(1000, "MAD")

    assert m1 < m2
    assert m1 <= m2
    assert m1 <= m3
    assert m2 > m1
    assert m2 >= m1
    assert m1 == m3
    assert m1 != m2

def test_calculate_tax_rounding():
    # 105 cents at 20% TVA: 105 * 0.20 = 21.0 -> 21
    assert calculate_tax(105, 20) == 21
    # 103 cents at 20% TVA: 103 * 0.20 = 20.6 -> 21 (ROUND_HALF_UP)
    assert calculate_tax(103, 20) == 21
    # 102 cents at 20% TVA: 102 * 0.20 = 20.4 -> 20
    assert calculate_tax(102, 20) == 20

def test_calculate_discount_rounding():
    # 1000 cents with 15% discount -> 150 cents
    assert calculate_discount(1000, 15) == 150
    # 999 cents with 10% discount -> 99.9 -> 100 cents
    assert calculate_discount(999, 10) == 100

def test_calculate_margin_percent():
    # Revenue 100, Cost 60 -> Margin 40.00%
    margin = calculate_margin_percent(10000, 6000)
    assert margin == Decimal("40.00")

    # Zero revenue -> 0.00%
    assert calculate_margin_percent(0, 1000) == Decimal("0.00")

    # Negative margin (selling below cost)
    neg_margin = calculate_margin_percent(5000, 10000)
    assert neg_margin == Decimal("-100.00")

def test_deterministic_terms_hash_stability():
    items = [
        {
            "sku_snapshot": "SRV-AI-4B",
            "quantity": 2,
            "unit_price_cents": 350000,
            "discount_percent": Decimal("10.00"),
            "discount_cents": 70000,
            "tax_cents": 126000,
            "total_cents": 756000
        },
        {
            "sku_snapshot": "LIC-VOICE-SIP",
            "quantity": 1,
            "unit_price_cents": 120000,
            "discount_percent": Decimal("0.00"),
            "discount_cents": 0,
            "tax_cents": 24000,
            "total_cents": 144000
        }
    ]

    h1 = PricingService.compute_terms_hash(
        items=items,
        subtotal_cents=820000,
        discount_total_cents=70000,
        tax_total_cents=150000,
        grand_total_cents=900000,
        currency="MAD",
        payment_terms="NET_30"
    )

    # Recomputing with identical items must produce identical hash
    h2 = PricingService.compute_terms_hash(
        items=list(reversed(items)),  # Order should not matter due to canonical sorting
        subtotal_cents=820000,
        discount_total_cents=70000,
        tax_total_cents=150000,
        grand_total_cents=900000,
        currency="MAD",
        payment_terms="NET_30"
    )
    assert h1 == h2

    # Any single value mutation must produce a different hash
    h3 = PricingService.compute_terms_hash(
        items=items,
        subtotal_cents=820000,
        discount_total_cents=70000,
        tax_total_cents=150000,
        grand_total_cents=900001,  # 1 cent difference
        currency="MAD",
        payment_terms="NET_30"
    )
    assert h1 != h3
