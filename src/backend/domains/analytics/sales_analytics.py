"""
Sales Analytics Domain Service.
Calculates revenue, conversion funnels, pipeline valuations, and representative performance.
Enforces multi-currency partitioning and timezone normalization (Africa/Casablanca).
(Controls 05-07, 28, 35, 42-43; Invariants 2, 3, 4)
"""
from datetime import datetime, date, timedelta, timezone
from typing import Dict, Any, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, case

from src.backend.models.entities import (
    SalesOrder,
    Opportunity,
    Lead,
    Quote,
    RefundRequest,
    User,
    AnalyticsDailySales,
    AnalyticsPipelineSnapshot
)


class SalesAnalyticsService:
    def __init__(self, session: AsyncSession, tenant_id: str):
        self.session = session
        self.tenant_id = tenant_id

    async def get_executive_overview(self, currency: str = "MAD") -> Dict[str, Any]:
        """
        Returns high-level executive sales KPIs:
        Gross revenue, net revenue, active deals count, total pipeline value,
        weighted pipeline value, and average deal value.
        """
        # 1. Gross Revenue & Order Count
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
                SalesOrder.currency == currency
            )
        )
        order_res = (await self.session.execute(order_stmt)).one()
        gross_rev = int(order_res.confirmed_revenue)
        confirmed_orders = int(order_res.confirmed_orders)

        # 2. Approved Refunds
        refund_stmt = select(
            func.coalesce(func.sum(RefundRequest.amount_cents), 0)
        ).where(
            and_(
                RefundRequest.tenant_id == self.tenant_id,
                RefundRequest.status.in_(["APPROVED", "COMPLETED"])
            )
        )
        refund_cents = int((await self.session.execute(refund_stmt)).scalar() or 0)
        net_rev = max(0, gross_rev - refund_cents)

        # 3. Pipeline Value & Weighted Value
        opp_stmt = select(
            func.coalesce(func.sum(Opportunity.amount_cents), 0).label("pipeline_nominal"),
            func.coalesce(func.sum(Opportunity.amount_cents * Opportunity.probability_percent / 100.0), 0).label("pipeline_weighted"),
            func.count(Opportunity.id).label("active_deals")
        ).where(
            and_(
                Opportunity.tenant_id == self.tenant_id,
                Opportunity.stage.notin_(["CLOSED_WON", "CLOSED_LOST"]),
                Opportunity.currency == currency
            )
        )
        opp_res = (await self.session.execute(opp_stmt)).one()
        pipeline_nominal = int(opp_res.pipeline_nominal)
        pipeline_weighted = int(opp_res.pipeline_weighted)
        active_deals = int(opp_res.active_deals)

        # 4. Average Deal Value (ADV)
        adv_cents = (gross_rev // confirmed_orders) if confirmed_orders > 0 else 0

        return {
            "tenant_id": self.tenant_id,
            "currency": currency,
            "gross_revenue_cents": gross_rev,
            "gross_revenue_display": f"{gross_rev / 100:.2f} {currency}",
            "refund_total_cents": refund_cents,
            "net_revenue_cents": net_rev,
            "net_revenue_display": f"{net_rev / 100:.2f} {currency}",
            "confirmed_orders_count": confirmed_orders,
            "active_pipeline_value_cents": pipeline_nominal,
            "active_pipeline_display": f"{pipeline_nominal / 100:.2f} {currency}",
            "weighted_pipeline_value_cents": pipeline_weighted,
            "weighted_pipeline_display": f"{pipeline_weighted / 100:.2f} {currency}",
            "active_deals_count": active_deals,
            "average_deal_value_cents": adv_cents,
            "average_deal_value_display": f"{adv_cents / 100:.2f} {currency}",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    async def get_conversion_funnel(self) -> Dict[str, Any]:
        """
        Calculates conversion progression across standard enterprise sales stages:
        Leads -> Qualified -> Quotes Issued -> Won Orders.
        """
        # Leads count
        leads_total = (await self.session.execute(
            select(func.count(Lead.id)).where(Lead.tenant_id == self.tenant_id)
        )).scalar() or 0

        qualified_leads = (await self.session.execute(
            select(func.count(Lead.id)).where(
                and_(Lead.tenant_id == self.tenant_id, Lead.status.in_(["QUALIFIED", "CONVERTED"]))
            )
        )).scalar() or 0

        # Quotes issued
        quotes_count = (await self.session.execute(
            select(func.count(Quote.id)).where(Quote.tenant_id == self.tenant_id)
        )).scalar() or 0

        accepted_quotes = (await self.session.execute(
            select(func.count(Quote.id)).where(
                and_(Quote.tenant_id == self.tenant_id, Quote.status == "ACCEPTED")
            )
        )).scalar() or 0

        # Confirmed sales orders
        won_orders = (await self.session.execute(
            select(func.count(SalesOrder.id)).where(
                and_(SalesOrder.tenant_id == self.tenant_id, SalesOrder.status.in_(["CONFIRMED", "SHIPPED", "DELIVERED", "COMPLETED"]))
            )
        )).scalar() or 0

        # Calculate conversion percentages safely
        qual_rate = round((qualified_leads / leads_total * 100.0), 1) if leads_total > 0 else 0.0
        quote_rate = round((quotes_count / qualified_leads * 100.0), 1) if qualified_leads > 0 else 0.0
        win_rate = round((won_orders / quotes_count * 100.0), 1) if quotes_count > 0 else 0.0
        overall_conversion = round((won_orders / leads_total * 100.0), 1) if leads_total > 0 else 0.0

        return {
            "total_leads": leads_total,
            "qualified_leads": qualified_leads,
            "quotes_count": quotes_count,
            "won_orders": won_orders,
            "qualification_rate_pct": qual_rate,
            "win_rate_pct": win_rate,
            "stages": [
                {"stage": "Captured Leads", "count": leads_total, "step_conversion_pct": 100.0},
                {"stage": "Qualified Leads", "count": qualified_leads, "step_conversion_pct": qual_rate},
                {"stage": "Quotations Issued", "count": quotes_count, "step_conversion_pct": quote_rate},
                {"stage": "Quotations Accepted", "count": accepted_quotes, "step_conversion_pct": round(accepted_quotes / quotes_count * 100.0, 1) if quotes_count > 0 else 0.0},
                {"stage": "Closed Won Orders", "count": won_orders, "step_conversion_pct": win_rate}
            ],
            "overall_conversion_pct": overall_conversion
        }

    async def get_pipeline_by_stage(self, currency: str = "MAD") -> List[Dict[str, Any]]:
        """Returns opportunities grouped by stage with nominal and probability-weighted values."""
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
        result = []
        for r in rows:
            tot = int(r.total_cents)
            wt = int(r.weighted_cents)
            result.append({
                "stage": r.stage,
                "deal_count": int(r.count),
                "total_value_cents": tot,
                "total_value_display": f"{tot / 100:.2f} {currency}",
                "weighted_value_cents": wt,
                "weighted_value_display": f"{wt / 100:.2f} {currency}"
            })
        return result

    async def get_sales_rep_performance(self, currency: str = "MAD") -> List[Dict[str, Any]]:
        """Returns performance metrics aggregated by sales representative."""
        stmt = select(
            User.id.label("rep_id"),
            User.full_name.label("rep_name"),
            func.count(SalesOrder.id).label("orders_count"),
            func.coalesce(func.sum(SalesOrder.grand_total_cents), 0).label("revenue_cents")
        ).join(
            SalesOrder, SalesOrder.created_by_user_id == User.id
        ).where(
            and_(
                User.tenant_id == self.tenant_id,
                SalesOrder.status.in_(["CONFIRMED", "SHIPPED", "DELIVERED", "COMPLETED"]),
                SalesOrder.currency == currency
            )
        ).group_by(User.id, User.full_name).order_by(func.sum(SalesOrder.grand_total_cents).desc())

        rows = (await self.session.execute(stmt)).all()
        reps = []
        for r in rows:
            rev = int(r.revenue_cents)
            reps.append({
                "rep_id": r.rep_id,
                "rep_name": r.rep_name,
                "orders_count": int(r.orders_count),
                "revenue_cents": rev,
                "revenue_display": f"{rev / 100:.2f} {currency}"
            })
        return reps

    async def get_revenue_timeseries(self, days: int = 30, currency: str = "MAD") -> List[Dict[str, Any]]:
        """
        Returns daily revenue time series for the past N days.
        Prefers pre-aggregated `analytics_daily_sales` read-model if available;
        falls back to direct operational aggregation.
        """
        start_date = date.today() - timedelta(days=days)

        # Query read-model
        stmt = select(
            AnalyticsDailySales.date,
            AnalyticsDailySales.total_revenue_cents,
            AnalyticsDailySales.net_revenue_cents,
            AnalyticsDailySales.paid_order_count
        ).where(
            and_(
                AnalyticsDailySales.tenant_id == self.tenant_id,
                AnalyticsDailySales.date >= start_date,
                AnalyticsDailySales.currency == currency
            )
        ).order_by(AnalyticsDailySales.date.asc())

        rows = (await self.session.execute(stmt)).all()
        if rows:
            return [
                {
                    "date": str(r.date),
                    "gross_revenue_cents": int(r.total_revenue_cents),
                    "net_revenue_cents": int(r.net_revenue_cents),
                    "orders_count": int(r.paid_order_count),
                    "currency": currency
                }
                for r in rows
            ]

        # Operational fallback
        op_stmt = select(
            func.date(SalesOrder.created_at).label("day"),
            func.coalesce(func.sum(SalesOrder.grand_total_cents), 0).label("revenue"),
            func.count(SalesOrder.id).label("count")
        ).where(
            and_(
                SalesOrder.tenant_id == self.tenant_id,
                SalesOrder.created_at >= datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc),
                SalesOrder.status.in_(["CONFIRMED", "SHIPPED", "DELIVERED", "COMPLETED"]),
                SalesOrder.currency == currency
            )
        ).group_by(func.date(SalesOrder.created_at)).order_by(func.date(SalesOrder.created_at).asc())

        op_rows = (await self.session.execute(op_stmt)).all()
        return [
            {
                "date": str(r.day),
                "gross_revenue_cents": int(r.revenue),
                "net_revenue_cents": int(r.revenue),
                "orders_count": int(r.count),
                "currency": currency
            }
            for r in op_rows
        ]
