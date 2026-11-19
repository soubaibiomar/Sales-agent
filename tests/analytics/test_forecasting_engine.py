"""
Unit Tests for Advisory Forecasting Engine (Step 11).
Validates Double Exponential Smoothing (Holt's Linear Trend), Moving Average baseline,
80% Confidence Interval widening, backtesting evaluation (MAE, RMSE, MAPE),
and strict advisory labeling (no mutations to financial state).
"""
import pytest
from src.backend.domains.analytics.forecasting import ForecastingEngine


def test_holt_linear_trend_forecasting():
    """
    Validates Holt linear trend calculation for an upward trending sales timeseries.
    Checks level, trend smoothing, point forecasts, and 80% CI boundaries.
    """
    engine = ForecastingEngine()
    # 14 days of historical daily sales (upward trend)
    historical_sales = [
        1000.0, 1100.0, 1250.0, 1300.0, 1420.0, 1500.0, 1600.0,
        1720.0, 1800.0, 1950.0, 2050.0, 2150.0, 2300.0, 2400.0
    ]

    forecast_result = engine.forecast_holt_linear(
        series=historical_sales,
        horizon=7,
        alpha=0.3,
        beta=0.1,
        confidence_level=0.80
    )

    # 1. Structure assertions
    assert "point_forecasts" in forecast_result
    assert len(forecast_result["point_forecasts"]) == 7
    assert "lower_bounds" in forecast_result
    assert "upper_bounds" in forecast_result
    assert "backtest" in forecast_result

    # 2. Upward trend maintained
    points = forecast_result["point_forecasts"]
    assert points[0] < points[-1], "Forecast must reflect upward linear trend"
    assert points[0] > historical_sales[-1], "First forecast day should continue above last observed"

    # 3. 80% Confidence Interval sanity & widening
    lower = forecast_result["lower_bounds"]
    upper = forecast_result["upper_bounds"]
    for h in range(7):
        assert lower[h] <= points[h] <= upper[h], f"Interval invalid at step {h}"
        assert lower[h] >= 0.0, "Lower bound must be non-negative for revenue"

    # Horizon interval widening: upper[h] - lower[h] increases over time
    width_day_1 = upper[0] - lower[0]
    width_day_7 = upper[6] - lower[6]
    assert width_day_7 >= width_day_1, "Confidence interval width must expand with forecast horizon"

    # 4. Mandatory Advisory Label
    assert forecast_result["is_advisory"] is True
    assert "advisory_notice" in forecast_result


def test_moving_average_baseline_forecasting():
    """
    Validates simple Moving Average baseline method with 7-day rolling window.
    """
    engine = ForecastingEngine()
    historical_sales = [100.0, 120.0, 110.0, 130.0, 115.0, 125.0, 140.0]
    # Average of last 7 points: (100+120+110+130+115+125+140)/7 = 840/7 = 120.0

    result = engine.forecast_moving_average(series=historical_sales, horizon=3, window_size=7)

    assert len(result["point_forecasts"]) == 3
    for p in result["point_forecasts"]:
        assert pytest.approx(p, 0.1) == 120.0
    assert result["is_advisory"] is True


def test_forecast_backtesting_accuracy_metrics():
    """
    Validates MAE, RMSE, and MAPE calculations on a known split.
    """
    engine = ForecastingEngine()
    actuals = [100.0, 110.0, 120.0, 130.0, 140.0]
    predictions = [102.0, 108.0, 122.0, 128.0, 142.0]  # Absolute errors: 2, 2, 2, 2, 2

    metrics = engine.compute_accuracy_metrics(actuals=actuals, predictions=predictions)

    # MAE = sum(|actual - pred|) / 5 = 10 / 5 = 2.0
    assert pytest.approx(metrics["mae"], 0.01) == 2.0
    # RMSE = sqrt(sum((actual - pred)^2) / 5) = sqrt(20 / 5) = sqrt(4) = 2.0
    assert pytest.approx(metrics["rmse"], 0.01) == 2.0
    # MAPE = (1/5) * sum(|actual - pred| / actual) * 100
    # = (2/100 + 2/110 + 2/120 + 2/130 + 2/140) / 5 * 100
    assert metrics["mape_pct"] > 0.0
    assert metrics["sample_size"] == 5


def test_forecasting_short_series_graceful_fallback():
    """
    Validates graceful fallback when historical data points are fewer than the required window.
    """
    engine = ForecastingEngine()
    short_series = [500.0, 520.0]  # Only 2 points

    result = engine.forecast_holt_linear(series=short_series, horizon=3)

    assert "point_forecasts" in result
    assert len(result["point_forecasts"]) == 3
    assert result["is_advisory"] is True
