"""
Advisory Sales & Revenue Forecasting Engine.
Implements Double Exponential Smoothing (Holt's Linear Trend) and Moving Average baselines.
Computes prediction intervals (80% CI) and historical backtest error metrics (MAE, RMSE, MAPE).
Enforces Invariant: Forecasts are strictly advisory and non-authoritative.
(Controls 05, 42, 64; Invariant 2, 7)
"""
import math
from typing import List, Dict, Any, Tuple, Optional
from datetime import date, timedelta


class ForecastingEngine:
    """
    Statistically grounded, advisory sales forecasting.
    Never mutates commercial truth; outputs advisory forecasts with uncertainty bounds.
    """

    @staticmethod
    def moving_average(series: List[float], window_size: int = 7) -> List[float]:
        """Calculates simple moving average for baseline comparison."""
        if not series or window_size <= 0:
            return []
        result = []
        for i in range(len(series)):
            window = series[max(0, i - window_size + 1): i + 1]
            result.append(sum(window) / len(window))
        return result

    @staticmethod
    def holt_linear_exponential_smoothing(
        series: List[float],
        alpha: float = 0.3,
        beta: float = 0.1,
        periods_ahead: int = 14
    ) -> Tuple[List[float], List[float], List[float], float]:
        """
        Fits Holt's two-parameter linear trend model.
        Returns:
        - fitted_values (historical in-sample fit)
        - forecasts (out-of-sample point predictions)
        - errors (in-sample residuals)
        - residual_std (sample standard deviation of residuals for confidence bounds)
        """
        n = len(series)
        if n < 2:
            val = series[0] if n == 1 else 0.0
            return [val], [val] * periods_ahead, [0.0], 0.0

        # Initialize level and trend
        level = series[0]
        trend = series[1] - series[0]

        fitted = [level]
        residuals = [0.0]

        for t in range(1, n):
            last_level = level
            last_trend = trend
            actual = series[t]

            # In-sample one-step ahead forecast
            one_step_forecast = last_level + last_trend
            fitted.append(one_step_forecast)
            residuals.append(actual - one_step_forecast)

            # Update level and trend
            level = alpha * actual + (1.0 - alpha) * (last_level + last_trend)
            trend = beta * (level - last_level) + (1.0 - beta) * last_trend

        # Generate future forecasts: F_{t+h} = level + h * trend
        forecasts = []
        for h in range(1, periods_ahead + 1):
            pred = max(0.0, level + h * trend)
            forecasts.append(pred)

        # Compute residual standard error
        variance = sum(r * r for r in residuals[1:]) / max(1, (n - 2))
        residual_std = math.sqrt(variance)

        return fitted, forecasts, residuals, residual_std

    @classmethod
    def evaluate_backtest(cls, actual: List[float], fitted: List[float]) -> Dict[str, float]:
        """Calculates backtest validation error metrics: MAE, RMSE, and MAPE."""
        if not actual or not fitted or len(actual) != len(fitted):
            return {"mae": 0.0, "rmse": 0.0, "mape_pct": 0.0}

        n = len(actual)
        abs_errors = [abs(a - f) for a, f in zip(actual, fitted)]
        sq_errors = [(a - f) ** 2 for a, f in zip(actual, fitted)]
        
        # Percentage error avoiding division by zero
        pct_errors = [
            abs(a - f) / a for a, f in zip(actual, fitted) if a > 0
        ]

        mae = sum(abs_errors) / n
        rmse = math.sqrt(sum(sq_errors) / n)
        mape = (sum(pct_errors) / len(pct_errors) * 100.0) if pct_errors else 0.0

        return {
            "mae": round(mae, 2),
            "rmse": round(rmse, 2),
            "mape_pct": round(mape, 2)
        }

    @classmethod
    def generate_advisory_revenue_forecast(
        cls,
        historical_daily_revenue: List[Dict[str, Any]],
        periods_ahead: int = 14,
        currency: str = "MAD"
    ) -> Dict[str, Any]:
        """
        Produces a complete advisory revenue forecast with backtest metrics and 80% confidence bands.
        """
        if not historical_daily_revenue:
            # Fallback for empty history
            return {
                "is_advisory": True,
                "disclaimer": "Advisory forecast only. Not an authoritative commercial or inventory state.",
                "model_name": "Holt-Linear-Trend",
                "currency": currency,
                "backtest_metrics": {"mae": 0.0, "rmse": 0.0, "mape_pct": 0.0},
                "forecast_points": []
            }

        # Extract amounts in cents
        dates = [r.get("date") for r in historical_daily_revenue]
        values = [float(r.get("gross_revenue_cents", 0)) for r in historical_daily_revenue]

        fitted, point_forecasts, residuals, residual_std = cls.holt_linear_exponential_smoothing(
            values, alpha=0.35, beta=0.15, periods_ahead=periods_ahead
        )

        backtest = cls.evaluate_backtest(values, fitted)

        # Baseline comparison: Simple moving average (window=7)
        ma_baseline = cls.moving_average(values, window_size=7)
        baseline_backtest = cls.evaluate_backtest(values, ma_baseline)

        # Construct future dates starting from tomorrow
        last_date = date.fromisoformat(str(dates[-1])) if dates[-1] else date.today()
        forecast_points = []

        # 80% Confidence Interval z-score is ~1.28
        z_80 = 1.28

        for h, point in enumerate(point_forecasts, start=1):
            f_date = last_date + timedelta(days=h)
            # Standard error widens with horizon: std * sqrt(1 + (h-1)*alpha)
            h_std = residual_std * math.sqrt(1.0 + (h - 1) * 0.35)
            lower_bound = max(0.0, point - z_80 * h_std)
            upper_bound = point + z_80 * h_std

            forecast_points.append({
                "date": str(f_date),
                "horizon_day": h,
                "predicted_revenue_cents": int(point),
                "lower_bound_cents": int(lower_bound),
                "upper_bound_cents": int(upper_bound),
                "predicted_display": f"{point / 100:.2f} {currency}",
                "lower_display": f"{lower_bound / 100:.2f} {currency}",
                "upper_display": f"{upper_bound / 100:.2f} {currency}"
            })

        return {
            "is_advisory": True,
            "disclaimer": "Advisory forecast only. Not an authoritative commercial or inventory state.",
            "model_name": "Holt-Linear-Trend-v1.0",
            "currency": currency,
            "sample_size_days": len(values),
            "backtest_metrics": backtest,
            "baseline_ma_metrics": baseline_backtest,
            "is_superior_to_baseline": backtest["rmse"] <= baseline_backtest["rmse"],
            "forecast_points": forecast_points
        }

    def forecast_holt_linear(
        self,
        series: List[float],
        horizon: int = 7,
        alpha: float = 0.3,
        beta: float = 0.1,
        confidence_level: float = 0.80
    ) -> Dict[str, Any]:
        """Convenience wrapper for Holt linear trend forecasting with prediction intervals."""
        fitted, point_forecasts, residuals, residual_std = self.holt_linear_exponential_smoothing(
            series=series, alpha=alpha, beta=beta, periods_ahead=horizon
        )
        z = 1.282 if confidence_level == 0.80 else 1.96
        lower = []
        upper = []
        for h, pt in enumerate(point_forecasts, start=1):
            h_std = residual_std * math.sqrt(1.0 + (h - 1) * 0.35)
            lb = max(0.0, pt - z * h_std)
            ub = pt + z * h_std
            lower.append(lb)
            upper.append(ub)

        backtest = self.evaluate_backtest(series, fitted)
        return {
            "point_forecasts": point_forecasts,
            "lower_bounds": lower,
            "upper_bounds": upper,
            "backtest": backtest,
            "is_advisory": True,
            "advisory_notice": "Statistically grounded advisory forecast. Does not mutate financial or inventory truth."
        }

    def forecast_moving_average(
        self,
        series: List[float],
        horizon: int = 3,
        window_size: int = 7
    ) -> Dict[str, Any]:
        """Convenience wrapper for moving average forecasting baseline."""
        ma = self.moving_average(series, window_size=window_size)
        last_val = ma[-1] if ma else (series[-1] if series else 0.0)
        return {
            "point_forecasts": [last_val] * horizon,
            "is_advisory": True,
            "advisory_notice": "Advisory moving average baseline."
        }

    def compute_accuracy_metrics(
        self,
        actuals: List[float],
        predictions: List[float]
    ) -> Dict[str, Any]:
        """Calculates MAE, RMSE, and MAPE with sample size."""
        metrics = self.evaluate_backtest(actuals, predictions)
        metrics["sample_size"] = len(actuals)
        return metrics
