"""
Unit Tests for Inventory ATP, Stock Holds, Expiry, Minor-Unit Money, and Invoice Hashing.
Step 05: Sprint 3 - Transact
"""
import pytest
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from src.backend.models.entities import InventoryItem, StockReservation, SalesOrder, Invoice
from src.backend.domains.pricing.money import Money, calculate_tax, calculate_discount
from src.backend.domains.invoicing.service import InvoicingService
from src.backend.domains.pricing.service import PricingService


def test_inventory_atp_property():
    item = InventoryItem(
        tenant_id="tenant_1",
        warehouse_id="wh_1",
        sku="SERVER-RACK-42U",
        on_hand_quantity=10,
        reserved_quantity=3,
        allocated_quantity=2,
        backorder_allowed=False
    )
    # Available-To-Promise = 10 - 3 - 2 = 5
    assert item.available_to_promise == 5

    # When reserved exceeds on-hand, ATP is 0 (never negative)
    item.reserved_quantity = 15
    assert item.available_to_promise == 0


def test_money_minor_unit_financial_precision():
    # Strict integer cents representation: 100.50 USD is 10050 cents
    price = Money(10050, "USD")
    assert price.amount_cents == 10050
    assert price.to_major() == Decimal("100.50")
    assert str(price) == "USD 100.50"

    # Strict prohibition of float math
    with pytest.raises(TypeError, match="Floating point multiplication is strictly forbidden"):
        _ = price * 1.25


def test_tax_and_discount_deterministic_rounding():
    # Unit price $19.99 = 1999 cents, qty = 3, discount = 15%
    unit_price = 1999
    qty = 3
    discount_pct = Decimal("15.00")
    tax_pct = Decimal("20.00")

    subtotal = unit_price * qty  # 5997 cents
    discount_cents = calculate_discount(subtotal, discount_pct)  # 5997 * 0.15 = 899.55 -> 900 cents
    assert discount_cents == 900

    net_subtotal = subtotal - discount_cents  # 5097 cents
    tax_cents = calculate_tax(net_subtotal, tax_pct)  # 5097 * 0.20 = 1019.4 -> 1019 cents
    assert tax_cents == 1019

    grand_total = net_subtotal + tax_cents  # 6116 cents ($61.16)
    assert grand_total == 6116


def test_invoice_canonical_hash_stability():
    items = [
        {"sku": "SKU-B", "name": "B-Item", "quantity": 1, "unit_price_cents": 2000, "total_cents": 2400},
        {"sku": "SKU-A", "name": "A-Item", "quantity": 2, "unit_price_cents": 1000, "total_cents": 2400}
    ]
    hash1 = InvoicingService.compute_invoice_hash(
        invoice_number="INV-2026-00001",
        currency="USD",
        subtotal_cents=4000,
        discount_total_cents=0,
        tax_total_cents=800,
        grand_total_cents=4800,
        items=items
    )

    # Shuffled input order must produce the exact same hash (canonical sorting)
    items_shuffled = [items[1], items[0]]
    hash2 = InvoicingService.compute_invoice_hash(
        invoice_number="INV-2026-00001",
        currency="USD",
        subtotal_cents=4000,
        discount_total_cents=0,
        tax_total_cents=800,
        grand_total_cents=4800,
        items=items_shuffled
    )
    assert hash1 == hash2
    assert len(hash1) == 64  # SHA-256


def test_invoice_canonical_hash_tamper_detection():
    items = [{"sku": "SKU-A", "name": "A-Item", "quantity": 1, "unit_price_cents": 1000, "total_cents": 1200}]
    original_hash = InvoicingService.compute_invoice_hash(
        invoice_number="INV-2026-00001",
        currency="USD",
        subtotal_cents=1000,
        discount_total_cents=0,
        tax_total_cents=200,
        grand_total_cents=1200,
        items=items
    )

    # Any modification to price or totals changes the hash
    tampered_hash = InvoicingService.compute_invoice_hash(
        invoice_number="INV-2026-00001",
        currency="USD",
        subtotal_cents=1000,
        discount_total_cents=0,
        tax_total_cents=200,
        grand_total_cents=1201,  # 1 cent tampered
        items=items
    )
    assert original_hash != tampered_hash
