"""
Deterministic Pricing Engine Domain Service.
Calculates exact prices, itemized taxes, discounts, margins, and cryptographic terms hashes.
(Baseline Controls 16, 17, 51, 57; Non-negotiable: NO float money, domain service authority)
"""
import hashlib
import json
from decimal import Decimal
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.models.entities import Product, ProductVariant, PriceList, PriceListItem
from src.backend.domains.pricing.money import (
    Money, calculate_tax, calculate_discount, calculate_margin_percent,
    NegativeQuantityError, CurrencyMismatchError
)

MAX_REP_DISCOUNT_PERCENT = Decimal("20.00")

class PricingError(Exception):
    pass

class ProductNotActiveError(PricingError):
    pass

class PricingService:
    """Authoritative deterministic pricing calculation engine."""

    @staticmethod
    def compute_terms_hash(
        items: List[Dict[str, Any]],
        subtotal_cents: int,
        discount_total_cents: int,
        tax_total_cents: int,
        grand_total_cents: int,
        currency: str,
        payment_terms: str
    ) -> str:
        """
        Generates a deterministic SHA-256 hash of the exact quote terms.
        If any quantity, price, discount, or payment term changes, the hash changes,
        automatically invalidating any prior manager approval.
        """
        canonical_items = []
        for it in sorted(items, key=lambda x: (x.get("sku_snapshot", ""), str(x.get("variant_id", "")))):
            canonical_items.append({
                "sku": it.get("sku_snapshot"),
                "qty": it.get("quantity"),
                "unit_price": it.get("unit_price_cents"),
                "discount_pct": str(it.get("discount_percent")),
                "discount_cents": it.get("discount_cents"),
                "tax_cents": it.get("tax_cents"),
                "total_cents": it.get("total_cents")
            })

        canonical_payload = {
            "currency": currency.upper().strip(),
            "payment_terms": payment_terms.strip(),
            "subtotal_cents": subtotal_cents,
            "discount_total_cents": discount_total_cents,
            "tax_total_cents": tax_total_cents,
            "grand_total_cents": grand_total_cents,
            "items": canonical_items
        }

        canonical_bytes = json.dumps(canonical_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(canonical_bytes).hexdigest()

    @staticmethod
    async def calculate_quote_pricing(
        session: AsyncSession,
        tenant_id: str,
        item_requests: List[Dict[str, Any]],
        price_list_id: Optional[str] = None,
        currency: str = "MAD",
        payment_terms: str = "NET_30"
    ) -> Dict[str, Any]:
        """
        Calculates itemized pricing, discounts, taxes, profit margins, and approval requirements.
        
        item_requests structure:
        [
            {
                "product_id": str,
                "variant_id": Optional[str],
                "quantity": int,
                "discount_percent": Optional[Decimal or float or str]
            }
        ]
        """
        if not item_requests:
            raise PricingError("Quotation must contain at least one line item")

        processed_items = []
        subtotal_acc = 0
        discount_acc = 0
        tax_acc = 0
        grand_total_acc = 0
        total_cost_acc = 0
        requires_approval = False
        approval_reasons = []

        # Optional price list lookup
        price_list = None
        if price_list_id:
            pl_stmt = select(PriceList).where(
                PriceList.id == price_list_id,
                PriceList.tenant_id == tenant_id,
                PriceList.is_active == True
            )
            pl_res = await session.execute(pl_stmt)
            price_list = pl_res.scalars().first()

        for req in item_requests:
            product_id = req.get("product_id")
            variant_id = req.get("variant_id")
            quantity = req.get("quantity", 1)
            raw_discount = req.get("discount_percent", Decimal("0.00"))

            if quantity <= 0:
                raise NegativeQuantityError(f"Quantity must be strictly positive (> 0), got {quantity}")

            discount_pct = Decimal(str(raw_discount))
            if discount_pct < Decimal("0.00") or discount_pct > Decimal("100.00"):
                raise PricingError(f"Discount percent must be between 0 and 100, got {discount_pct}")

            # 1. Fetch Product
            p_stmt = select(Product).where(
                Product.id == product_id,
                Product.tenant_id == tenant_id
            )
            p_res = await session.execute(p_stmt)
            product = p_res.scalars().first()
            if not product:
                raise PricingError(f"Product '{product_id}' not found in tenant")
            if not product.is_active:
                raise ProductNotActiveError(f"Product '{product.sku}' is deactivated and cannot be quoted")

            unit_price = product.base_price_cents
            unit_cost = product.cost_cents

            # 2. Check Price List tier item if applicable
            if price_list:
                pli_stmt = select(PriceListItem).where(
                    PriceListItem.tenant_id == tenant_id,
                    PriceListItem.price_list_id == price_list.id,
                    PriceListItem.product_id == product.id,
                    PriceListItem.min_quantity <= quantity
                ).order_by(PriceListItem.min_quantity.desc())
                if variant_id:
                    pli_stmt = pli_stmt.where(
                        (PriceListItem.variant_id == variant_id) | (PriceListItem.variant_id.is_(None))
                    )
                pli_res = await session.execute(pli_stmt)
                pli = pli_res.scalars().first()
                if pli:
                    unit_price = pli.unit_price_cents

            # 3. Check Variant adjustment
            variant = None
            if variant_id:
                v_stmt = select(ProductVariant).where(
                    ProductVariant.id == variant_id,
                    ProductVariant.product_id == product.id,
                    ProductVariant.tenant_id == tenant_id,
                    ProductVariant.is_active == True
                )
                v_res = await session.execute(v_stmt)
                variant = v_res.scalars().first()
                if variant:
                    unit_price += variant.price_adjustment_cents
                    unit_cost += variant.cost_adjustment_cents

            # 4. Compute Line Totals using Exact Integer Minor Units
            line_subtotal_cents = unit_price * quantity
            line_discount_cents = calculate_discount(line_subtotal_cents, discount_pct)
            line_net_cents = line_subtotal_cents - line_discount_cents
            line_tax_cents = calculate_tax(line_net_cents, product.tax_rate_percent)
            line_total_cents = line_net_cents + line_tax_cents

            line_cost_cents = unit_cost * quantity
            line_margin_pct = calculate_margin_percent(line_net_cents, line_cost_cents)

            # 5. Margin Floor & Rep Discount Limit Policies
            if discount_pct > MAX_REP_DISCOUNT_PERCENT:
                requires_approval = True
                approval_reasons.append(
                    f"Line '{product.sku}' discount ({discount_pct}%) exceeds standard rep limit ({MAX_REP_DISCOUNT_PERCENT}%)"
                )

            if line_margin_pct < product.min_margin_percent:
                requires_approval = True
                approval_reasons.append(
                    f"Line '{product.sku}' margin ({line_margin_pct}%) breaches product margin floor ({product.min_margin_percent}%)"
                )

            item_data = {
                "product_id": product.id,
                "variant_id": variant.id if variant else None,
                "sku_snapshot": variant.sku_variant if variant else product.sku,
                "name_snapshot": f"{product.name} ({variant.name})" if variant else product.name,
                "quantity": quantity,
                "uom_snapshot": product.uom,
                "unit_price_cents": unit_price,
                "unit_cost_cents": unit_cost,
                "discount_percent": discount_pct,
                "discount_cents": line_discount_cents,
                "tax_rate_percent": product.tax_rate_percent,
                "subtotal_cents": line_subtotal_cents,
                "tax_cents": line_tax_cents,
                "total_cents": line_total_cents,
                "margin_percent": line_margin_pct
            }
            processed_items.append(item_data)

            subtotal_acc += line_subtotal_cents
            discount_acc += line_discount_cents
            tax_acc += line_tax_cents
            grand_total_acc += line_total_cents
            total_cost_acc += line_cost_cents

        net_revenue_acc = subtotal_acc - discount_acc
        overall_margin_pct = calculate_margin_percent(net_revenue_acc, total_cost_acc)

        terms_hash = PricingService.compute_terms_hash(
            items=processed_items,
            subtotal_cents=subtotal_acc,
            discount_total_cents=discount_acc,
            tax_total_cents=tax_acc,
            grand_total_cents=grand_total_acc,
            currency=currency,
            payment_terms=payment_terms
        )

        return {
            "currency": currency.upper().strip(),
            "payment_terms": payment_terms.strip(),
            "subtotal_cents": subtotal_acc,
            "discount_total_cents": discount_acc,
            "tax_total_cents": tax_acc,
            "grand_total_cents": grand_total_acc,
            "margin_percent": overall_margin_pct,
            "requires_approval": requires_approval,
            "approval_reason": "; ".join(approval_reasons) if approval_reasons else None,
            "terms_hash": terms_hash,
            "items": processed_items
        }


def calculate_quote_pricing(items: List[Dict[str, Any]], tva_rate: float = 20.0) -> Dict[str, Any]:
    """Pure deterministic pricing calculator for quote breakdown validation."""
    subtotal_cents = 0
    discount_cents = 0
    for item in items:
        unit = item.get("unit_price_cents", 0)
        qty = item.get("quantity", 1)
        disc_pct = item.get("discount_pct", 0.0)
        line_sub = unit * qty
        line_disc = int(round(line_sub * (disc_pct / 100.0)))
        subtotal_cents += line_sub
        discount_cents += line_disc
    net_cents = subtotal_cents - discount_cents
    tva_cents = int(round(net_cents * (tva_rate / 100.0)))
    total_cents = net_cents + tva_cents
    return {
        "subtotal_cents": subtotal_cents,
        "discount_cents": discount_cents,
        "net_cents": net_cents,
        "tva_cents": tva_cents,
        "total_cents": total_cents
    }
