"""
Analytics Aggregation Worker.
Performs idempotent incremental aggregation into read-model tables:
`analytics_daily_sales` and `analytics_pipeline_snapshots`.
Implements 72-hour watermark lookback to capture late cancellations, payments, and refunds.
(Controls 05-07, 28, 42-43; Invariants 2, 3, 4)
"""
import logging
from datetime import datetime, date, timedelta, timezone
from typing import Dict, Any, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, case

from src.backend.models.entities import (
    SalesOrder,
    RefundRequest,
    Opportunity,
    AnalyticsDailySales,
    AnalyticsPipelineSnapshot,
    generate_uuid
)

logger = logging.getLogger("SalesAI.AnalyticsWorker")


class AnalyticsAggregationWorker:
    def __init__(self, session: AsyncSession, tenant_id: str):
        self.session = session
        self.tenant_id = tenant_id

    async def aggregate_daily_sales_for_date(self, target_date: date, currency: str = "MAD") -> AnalyticsDailySales:
        """
        Aggregates sales orders and refunds for a single calendar day into `analytics_daily_sales`.
        Idempotent: updates existing record or creates a new one.
        """
        start_dt = datetime.combine(target_date, datetime.min.time(), tzinfo=timezone.utc)
        end_dt = datetime.combine(target_date, datetime.max.time(), tzinfo=timezone.utc)

        # 1. Orders and Confirmed Revenue
        order_stmt = select(
            func.coalesce(func.sum(SalesOrder.grand_total_cents), 0).label("gross_revenue"),
            func.count(SalesOrder.id).label("total_orders"),
            func.coalesce(func.sum(
                case((SalesOrder.status.in_(["CONFIRMED", "SHIPPED", "DELIVERED", "COMPLETED"]), SalesOrder.grand_total_cents), else_=0)
            ), 0).label("confirmed_revenue"),
            func.coalesce(func.count(
                case((SalesOrder.status.in_(["CONFIRMED", "SHIPPED", "DELIVERED", "COMPLETED"]), 1))
            ), 0).label("confirmed_orders")
        ).where(
            and_(
                SalesOrder.tenant_id == self.tenant_id,
                SalesOrder.currency == currency,
                SalesOrder.created_at >= start_dt,
                SalesOrder.created_at <= end_dt
            )
        )
        order_res = (await self.session.execute(order_stmt)).one()
        gross_rev = int(order_res.confirmed_revenue)
        confirmed_orders = int(order_res.confirmed_orders)
        total_orders = int(order_res.total_orders)

        # 2. Approved Refunds for this date
        refund_stmt = select(
            func.coalesce(func.sum(RefundRequest.amount_cents), 0).label("refund_cents"),
            func.count(RefundRequest.id).label("refund_count")
        ).where(
            and_(
                RefundRequest.tenant_id == self.tenant_id,
                RefundRequest.status.in_(["APPROVED", "COMPLETED"]),
                RefundRequest.created_at >= start_dt,
                RefundRequest.created_at <= end_dt
            )
        )
        ref_res = (await self.session.execute(refund_stmt)).one()
        refund_cents = int(ref_res.refund_cents)
        refund_count = int(ref_res.refund_count)

        net_rev = max(0, gross_rev - refund_cents)
        aov = (gross_rev // confirmed_orders) if confirmed_orders > 0 else 0

        # 3. Check for existing record
        exist_stmt = select(AnalyticsDailySales).where(
            and_(
                AnalyticsDailySales.tenant_id == self.tenant_id,
                AnalyticsDailySales.date == target_date,
                AnalyticsDailySales.currency == currency
            )
        )
        record = (await self.session.execute(exist_stmt)).scalar_one_or_none()

        if record:
            record.total_revenue_cents = gross_rev
            record.order_count = total_orders
            record.paid_order_count = confirmed_orders
            record.refund_count = refund_count
            record.refund_total_cents = refund_cents
            record.net_revenue_cents = net_rev
            record.average_order_value_cents = aov
            record.last_aggregated_at = datetime.now(timezone.utc)
        else:
            record = AnalyticsDailySales(
                id=generate_uuid(),
                tenant_id=self.tenant_id,
                date=target_date,
                total_revenue_cents=gross_rev,
                order_count=total_orders,
                paid_order_count=confirmed_orders,
                refund_count=refund_count,
                refund_total_cents=refund_cents,
                net_revenue_cents=net_rev,
                average_order_value_cents=aov,
                currency=currency,
                last_aggregated_at=datetime.now(timezone.utc)
            )
            self.session.add(record)

        await self.session.flush()
        return record

    async def snapshot_pipeline_stages(self, snapshot_date: date, currency: str = "MAD") -> List[AnalyticsPipelineSnapshot]:
        """
        Takes a snapshot of active opportunity pipeline stages for the tenant.
        """
        stmt = select(
            Opportunity.stage,
            func.count(Opportunity.id).label("count"),
            func.coalesce(func.sum(Opportunity.amount_cents), 0).label("total_cents"),
            func.coalesce(func.sum(Opportunity.amount_cents * Opportunity.probability_percent / 100.0), 0).label("weighted_cents")
        ).where(
            and_(
                Opportunity.tenant_id == self.tenant_id,
                Opportunity.currency == currency
            )
        ).group_by(Opportunity.stage)

        rows = (await self.session.execute(stmt)).all()
        snapshots = []

        for r in rows:
            exist_stmt = select(AnalyticsPipelineSnapshot).where(
                and_(
                    AnalyticsPipelineSnapshot.tenant_id == self.tenant_id,
                    AnalyticsPipelineSnapshot.snapshot_date == snapshot_date,
                    AnalyticsPipelineSnapshot.stage == r.stage,
                    AnalyticsPipelineSnapshot.currency == currency
                )
            )
            snap = (await self.session.execute(exist_stmt)).scalar_one_or_none()

            tot = int(r.total_cents)
            wt = int(r.weighted_cents)

            if snap:
                snap.deal_count = int(r.count)
                snap.total_value_cents = tot
                snap.weighted_value_cents = wt
            else:
                snap = AnalyticsPipelineSnapshot(
                    id=generate_uuid(),
                    tenant_id=self.tenant_id,
                    snapshot_date=snapshot_date,
                    stage=r.stage,
                    deal_count=int(r.count),
                    total_value_cents=tot,
                    weighted_value_cents=wt,
                    currency=currency
                )
                self.session.add(snap)
            snapshots.append(snap)

        await self.session.flush()
        return snapshots

    async def reconcile_watermark(self, lookback_days: int = 3, currency: str = "MAD") -> int:
        """
        Reconciles the past N days to guarantee that late cancellations, refunds, or delayed state transitions
        are accurately incorporated into the read models.
        """
        today = date.today()
        count = 0
        for i in range(lookback_days + 1):
            d = today - timedelta(days=i)
            await self.aggregate_daily_sales_for_date(d, currency=currency)
            count += 1
        await self.snapshot_pipeline_stages(today, currency=currency)
        await self.session.commit()
        logger.info(f"Watermark reconciliation complete for tenant {self.tenant_id}: {count} days reconciled.")
        return count
