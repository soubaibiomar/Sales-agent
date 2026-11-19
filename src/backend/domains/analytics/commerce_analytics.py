"""
Commerce & Operations Analytics Domain Service.
Calculates order statuses, payment reconciliation, stockout risks, fulfillment SLAs, and RMA rates.
(Controls 05-07, 28, 35, 42-43; Invariants 2, 3, 4)
"""
from datetime import datetime, timezone
from typing import Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from src.backend.models.entities import (
    SalesOrder,
    Invoice,
    PaymentTransaction,
    InventoryItem,
    Product,
    Shipment,
    ReturnAuthorization,
    SupportTicket
)


class CommerceAnalyticsService:
    def __init__(self, session: AsyncSession, tenant_id: str):
        self.session = session
        self.tenant_id = tenant_id

    async def get_order_status_distribution(self) -> Dict[str, Any]:
        """Returns distribution of all sales orders by status."""
        stmt = select(
            SalesOrder.status,
            func.count(SalesOrder.id).label("count"),
            func.coalesce(func.sum(SalesOrder.grand_total_cents), 0).label("value_cents")
        ).where(
            SalesOrder.tenant_id == self.tenant_id
        ).group_by(SalesOrder.status)

        rows = (await self.session.execute(stmt)).all()
        statuses = {}
        total_orders = 0
        total_value = 0
        for r in rows:
            cnt = int(r.count)
            val = int(r.value_cents)
            statuses[r.status] = {"count": cnt, "value_cents": val}
            total_orders += cnt
            total_value += val

        return {
            "total_orders": total_orders,
            "total_value_cents": total_value,
            "status_breakdown": statuses
        }

    async def get_payment_collection_metrics(self) -> Dict[str, Any]:
        """Calculates payment success and invoice collection rates."""
        # 1. Total Invoiced Value
        inv_stmt = select(
            func.coalesce(func.sum(Invoice.grand_total_cents), 0).label("invoiced_cents"),
            func.count(Invoice.id).label("invoices_count")
        ).where(
            and_(Invoice.tenant_id == self.tenant_id, Invoice.status != "CANCELLED")
        )
        inv_res = (await self.session.execute(inv_stmt)).one()
        invoiced_cents = int(inv_res.invoiced_cents)
        invoices_count = int(inv_res.invoices_count)

        # 2. Total Payments Collected (SUCCESS)
        pay_stmt = select(
            func.coalesce(func.sum(PaymentTransaction.amount_cents), 0).label("collected_cents"),
            func.count(PaymentTransaction.id).label("transactions_count"),
            func.coalesce(func.count(
                func.nullif(PaymentTransaction.status == "SUCCESS", False)
            ), 0).label("successful_count")
        ).where(
            PaymentTransaction.tenant_id == self.tenant_id
        )
        pay_res = (await self.session.execute(pay_stmt)).one()
        collected_cents = int(pay_res.collected_cents)
        tx_count = int(pay_res.transactions_count)
        tx_success = int(pay_res.successful_count)

        collection_rate = round((collected_cents / invoiced_cents * 100.0), 1) if invoiced_cents > 0 else 0.0
        tx_success_rate = round((tx_success / tx_count * 100.0), 1) if tx_count > 0 else 0.0

        return {
            "invoiced_total_cents": invoiced_cents,
            "invoices_count": invoices_count,
            "collected_total_cents": collected_cents,
            "collection_rate_pct": collection_rate,
            "transactions_count": tx_count,
            "successful_transactions_count": tx_success,
            "transaction_success_rate_pct": tx_success_rate
        }

    async def get_stockout_risk_items(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Identifies catalog products where stock quantity is below the reorder point."""
        stmt = select(
            Product.id.label("product_id"),
            Product.sku,
            Product.name,
            InventoryItem.on_hand_quantity,
            InventoryItem.reserved_quantity
        ).join(
            InventoryItem, InventoryItem.product_id == Product.id
        ).where(
            and_(
                Product.tenant_id == self.tenant_id,
                Product.is_active == True,
                (InventoryItem.on_hand_quantity - InventoryItem.reserved_quantity) <= 5
            )
        ).limit(limit)

        rows = (await self.session.execute(stmt)).all()
        results = []
        for r in rows:
            avail = int(r.on_hand_quantity) - int(r.reserved_quantity)
            results.append({
                "product_id": r.product_id,
                "sku": r.sku,
                "product_name": r.name,
                "quantity_on_hand": int(r.on_hand_quantity),
                "quantity_reserved": int(r.reserved_quantity),
                "available_quantity": avail,
                "reorder_point": 5,
                "status": "OUT_OF_STOCK" if avail <= 0 else "LOW_STOCK"
            })
        return results

    async def get_logistics_and_fulfillment_metrics(self) -> Dict[str, Any]:
        """Computes shipment delivery rate and fulfillment performance."""
        stmt = select(
            Shipment.status,
            func.count(Shipment.id).label("count")
        ).where(
            Shipment.tenant_id == self.tenant_id
        ).group_by(Shipment.status)

        rows = (await self.session.execute(stmt)).all()
        counts = {r.status: int(r.count) for r in rows}
        total_shipments = sum(counts.values())
        delivered = counts.get("DELIVERED", 0)

        delivery_rate = round((delivered / total_shipments * 100.0), 1) if total_shipments > 0 else 0.0

        return {
            "total_shipments": total_shipments,
            "delivered_count": delivered,
            "in_transit_count": counts.get("IN_TRANSIT", 0),
            "pending_count": counts.get("PENDING", 0),
            "delivery_success_rate_pct": delivery_rate
        }

    async def get_rma_and_support_metrics(self) -> Dict[str, Any]:
        """Computes return authorization (RMA) rates and support ticket statuses."""
        # 1. Total RMA count
        rma_count = (await self.session.execute(
            select(func.count(ReturnAuthorization.id)).where(ReturnAuthorization.tenant_id == self.tenant_id)
        )).scalar() or 0

        # Total completed orders
        orders_count = (await self.session.execute(
            select(func.count(SalesOrder.id)).where(
                and_(SalesOrder.tenant_id == self.tenant_id, SalesOrder.status.in_(["DELIVERED", "COMPLETED"]))
            )
        )).scalar() or 0

        rma_rate = round((rma_count / orders_count * 100.0), 2) if orders_count > 0 else 0.0

        # 2. Support tickets
        tix_stmt = select(
            SupportTicket.status,
            func.count(SupportTicket.id).label("count")
        ).where(
            SupportTicket.tenant_id == self.tenant_id
        ).group_by(SupportTicket.status)

        tix_rows = (await self.session.execute(tix_stmt)).all()
        tix_breakdown = {r.status: int(r.count) for r in tix_rows}
        open_tickets = tix_breakdown.get("OPEN", 0) + tix_breakdown.get("IN_PROGRESS", 0)

        return {
            "total_rma_requests": rma_count,
            "completed_orders_count": orders_count,
            "rma_rate_pct": rma_rate,
            "support_tickets_breakdown": tix_breakdown,
            "open_tickets_count": open_tickets
        }
