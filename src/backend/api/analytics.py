"""
Analytics API Router.
Exposes endpoints for executive overviews, revenue timeseries, conversion funnels,
pipeline snapshots, commerce metrics, and advisory revenue forecasting.
(Controls 05-07, 28, 35, 42-43; Invariants 2, 3, 4)
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.core.database import get_db_session
from src.backend.core.auth_middleware import get_security_context, SecurityContext
from src.backend.domains.analytics.sales_analytics import SalesAnalyticsService
from src.backend.domains.analytics.commerce_analytics import CommerceAnalyticsService
from src.backend.domains.analytics.forecasting import ForecastingEngine
from src.backend.domains.analytics.aggregation_worker import AnalyticsAggregationWorker

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get("/overview")
async def get_executive_overview(
    currency: str = Query("MAD", description="ISO Currency code"),
    ctx: SecurityContext = Depends(get_security_context),
    db: AsyncSession = Depends(get_db_session)
):
    """Returns top-level executive revenue and pipeline KPIs."""
    service = SalesAnalyticsService(db, ctx.tenant_id)
    return await service.get_executive_overview(currency=currency)


@router.get("/sales")
async def get_sales_analytics(
    days: int = Query(30, ge=1, le=365),
    currency: str = Query("MAD"),
    ctx: SecurityContext = Depends(get_security_context),
    db: AsyncSession = Depends(get_db_session)
):
    """Returns revenue timeseries, conversion funnel, and sales representative leaderboard."""
    service = SalesAnalyticsService(db, ctx.tenant_id)
    timeseries = await service.get_revenue_timeseries(days=days, currency=currency)
    funnel = await service.get_conversion_funnel()
    reps = await service.get_sales_rep_performance(currency=currency)

    return {
        "tenant_id": ctx.tenant_id,
        "currency": currency,
        "days": days,
        "revenue_trend": timeseries,
        "conversion_funnel": funnel,
        "rep_leaderboard": reps
    }


@router.get("/pipeline")
async def get_pipeline_analytics(
    currency: str = Query("MAD"),
    ctx: SecurityContext = Depends(get_security_context),
    db: AsyncSession = Depends(get_db_session)
):
    """Returns opportunity pipeline valuation breakdown by stage."""
    service = SalesAnalyticsService(db, ctx.tenant_id)
    stages = await service.get_pipeline_by_stage(currency=currency)
    return {
        "tenant_id": ctx.tenant_id,
        "currency": currency,
        "stages": stages
    }


@router.get("/commerce")
async def get_commerce_analytics(
    ctx: SecurityContext = Depends(get_security_context),
    db: AsyncSession = Depends(get_db_session)
):
    """Returns commerce health, payment collections, stockout risks, fulfillment, and RMA rates."""
    service = CommerceAnalyticsService(db, ctx.tenant_id)
    orders = await service.get_order_status_distribution()
    payments = await service.get_payment_collection_metrics()
    stockouts = await service.get_stockout_risk_items(limit=10)
    logistics = await service.get_logistics_and_fulfillment_metrics()
    rma = await service.get_rma_and_support_metrics()

    return {
        "tenant_id": ctx.tenant_id,
        "orders_summary": orders,
        "payments_summary": payments,
        "stockout_risks": stockouts,
        "logistics_fulfillment": logistics,
        "rma_and_support": rma
    }


@router.get("/forecast")
async def get_advisory_forecast(
    periods_ahead: int = Query(14, ge=1, le=90),
    currency: str = Query("MAD"),
    ctx: SecurityContext = Depends(get_security_context),
    db: AsyncSession = Depends(get_db_session)
):
    """
    Returns statistically grounded advisory revenue forecasts with 80% CI and backtest metrics.
    Enforces Invariant: Forecasts are strictly advisory and non-authoritative.
    """
    service = SalesAnalyticsService(db, ctx.tenant_id)
    timeseries = await service.get_revenue_timeseries(days=60, currency=currency)
    forecast = ForecastingEngine.generate_advisory_revenue_forecast(
        timeseries, periods_ahead=periods_ahead, currency=currency
    )
    return forecast


@router.post("/aggregate")
async def trigger_aggregation(
    lookback_days: int = Query(3, ge=1, le=30),
    currency: str = Query("MAD"),
    ctx: SecurityContext = Depends(get_security_context),
    db: AsyncSession = Depends(get_db_session)
):
    """Triggers on-demand incremental aggregation and watermark reconciliation."""
    worker = AnalyticsAggregationWorker(db, ctx.tenant_id)
    count = await worker.reconcile_watermark(lookback_days=lookback_days, currency=currency)
    return {
        "status": "SUCCESS",
        "tenant_id": ctx.tenant_id,
        "days_reconciled": count
    }
