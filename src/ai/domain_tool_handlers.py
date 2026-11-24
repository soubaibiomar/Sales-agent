"""
Domain-backed handlers for the AI Tool Gateway (inspection finding F-07).

The commercial-fact tools (catalog, stock, pricing, order/payment status) previously
returned hardcoded fixtures (e.g. every order "PAID", stock always 15), which the
OutputGuard then treated as verified evidence. These handlers answer from the
authoritative, tenant-scoped domain data instead. They never fall back to fixtures:
when the database is unavailable or the record does not exist they raise, the gateway
reports SERVICE_REJECTED and the agent has no evidence, so the guard blocks any
commercial claim (fail closed).

The tenant always comes from the server-issued ServerSecurityContext, never from
model-generated parameters.
"""
from typing import Any, Dict

from sqlalchemy import select, or_, func

from src.backend.models.entities import Product, InventoryItem, SalesOrder, Shipment

# Tools whose answers are customer-facing commercial facts and must be authoritative.
AUTHORITATIVE_FACT_TOOLS = ("catalog.search", "inventory.check_atp", "pricing.calculate_quote", "orders.get_status")


class ToolDataUnavailableError(Exception):
    """No authoritative data could be produced for this tool call."""


def _require_db(db_session):
    if db_session is None:
        raise ToolDataUnavailableError("No database session: authoritative data unavailable.")
    return db_session


async def handle_catalog_search(inp, ctx, db_session) -> Dict[str, Any]:
    db = _require_db(db_session)
    pattern = f"%{inp.query.strip().lower()}%"
    stmt = select(Product).where(
        Product.tenant_id == ctx.tenant_id,
        Product.is_active.is_(True),
        or_(func.lower(Product.name).like(pattern), func.lower(Product.sku).like(pattern))
    )
    if inp.category:
        stmt = stmt.where(Product.category == inp.category)
    rows = (await db.execute(stmt.order_by(Product.name.asc()).limit(inp.limit))).scalars().all()
    products = [
        {"sku": p.sku, "name": p.name, "price_cents": int(p.base_price_cents or 0), "currency": p.currency}
        for p in rows
    ]
    return {"products": products, "total_found": len(products), "source": "catalog_service"}


async def handle_inventory_atp(inp, ctx, db_session) -> Dict[str, Any]:
    db = _require_db(db_session)
    stmt = select(InventoryItem).where(
        InventoryItem.tenant_id == ctx.tenant_id,
        InventoryItem.sku == inp.sku.upper()
    )
    if inp.warehouse_id:
        stmt = stmt.where(InventoryItem.warehouse_id == inp.warehouse_id)
    items = (await db.execute(stmt)).scalars().all()
    if not items:
        raise ToolDataUnavailableError(f"SKU '{inp.sku}' is not stocked for this tenant.")
    available = sum(i.available_to_promise for i in items)
    return {"sku": inp.sku.upper(), "available_units": int(available), "is_in_stock": available > 0,
            "currency": "MAD", "source": "inventory_ledger"}


async def handle_pricing_quote(inp, ctx, db_session) -> Dict[str, Any]:
    from src.backend.domains.pricing.service import PricingService
    db = _require_db(db_session)
    requests = []
    for line in inp.items:
        sku = str(line.get("sku", "")).strip()
        qty = int(line.get("quantity", 0))
        if not sku or qty <= 0:
            raise ToolDataUnavailableError("Each pricing line needs a SKU and a positive quantity.")
        product = (await db.execute(select(Product).where(
            Product.tenant_id == ctx.tenant_id, Product.sku == sku
        ))).scalars().first()
        if not product:
            raise ToolDataUnavailableError(f"Unknown SKU '{sku}'.")
        requests.append({"product_id": product.id, "quantity": qty})
    # Discounts are never taken from the model: only the pricing service's own rules apply.
    priced = await PricingService.calculate_quote_pricing(session=db, tenant_id=ctx.tenant_id, item_requests=requests)
    return {
        "subtotal_cents": int(priced["subtotal_cents"]),
        "discount_cents": int(priced["discount_total_cents"]),
        "tax_cents": int(priced["tax_total_cents"]),
        "total_cents": int(priced["grand_total_cents"]),
        "currency": priced["currency"],
        "items": priced["items"],
        "applied_rules": ["PRICING_SERVICE"] + (["REQUIRES_APPROVAL"] if priced["requires_approval"] else []),
    }


async def handle_order_status(inp, ctx, db_session) -> Dict[str, Any]:
    db = _require_db(db_session)
    order = (await db.execute(select(SalesOrder).where(
        SalesOrder.tenant_id == ctx.tenant_id,
        or_(SalesOrder.id == inp.order_id, SalesOrder.order_number == inp.order_id)
    ))).scalars().first()
    if not order:
        raise ToolDataUnavailableError(f"Order '{inp.order_id}' not found.")
    shipment = (await db.execute(select(Shipment).where(
        Shipment.tenant_id == ctx.tenant_id, Shipment.order_id == order.id
    ).order_by(Shipment.created_at.desc()))).scalars().first()
    return {
        "order_id": order.order_number or order.id,
        "order_status": order.status,
        "payment_status": order.payment_status,
        "total_cents": int(order.grand_total_cents or 0),
        "currency": order.currency,
        "tracking_number": shipment.tracking_number if shipment else None,
    }


def register_domain_tool_handlers(gateway) -> None:
    gateway.register_handler("catalog.search", handle_catalog_search)
    gateway.register_handler("inventory.check_atp", handle_inventory_atp)
    gateway.register_handler("pricing.calculate_quote", handle_pricing_quote)
    gateway.register_handler("orders.get_status", handle_order_status)
