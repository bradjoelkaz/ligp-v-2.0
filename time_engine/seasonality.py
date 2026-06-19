"""Seasonality detection (QA-016).

Primary backend is Facebook Prophet (lazy import). When Prophet is unavailable
(e.g. the offline sandbox), a deterministic day-of-week + month seasonal index
computed from the supplied history is used so the API stays functional and
unit-testable. ``get_seasonal_boost`` always returns a value in [0.5, 2.0].
"""

from __future__ import annotations

import statistics
from datetime import datetime
from typing import Any

from utils.helpers import clamp
from utils.logger import get_logger

_log = get_logger(__name__)

_BOOST_MIN = 0.5
_BOOST_MAX = 2.0


class SeasonalityDetector:
    """Fit a seasonal model and expose boost factors / forecasts."""

    def __init__(self) -> None:
        self._prophet_model: Any | None = None
        self._dow_index: dict[int, float] = {}
        self._month_index: dict[int, float] = {}
        self._fitted = False
        self._history: list[tuple[datetime, float]] = []

    def fit(self, dates: list[datetime], values: list[float]) -> None:
        """Fit Prophet if available; always compute the heuristic fallback."""
        if len(dates) != len(values):
            raise ValueError("dates and values must be the same length")
        self._history = list(zip(dates, values, strict=True))
        self._fit_heuristic(dates, values)
        self._try_fit_prophet(dates, values)
        self._fitted = True

    def _fit_heuristic(self, dates: list[datetime], values: list[float]) -> None:
        overall = statistics.mean(values) if values else 0.0
        dow_buckets: dict[int, list[float]] = {}
        month_buckets: dict[int, list[float]] = {}
        for d, v in zip(dates, values, strict=True):
            dow_buckets.setdefault(d.weekday(), []).append(v)
            month_buckets.setdefault(d.month, []).append(v)

        self._dow_index = {
            k: (statistics.mean(vs) / overall if overall else 1.0) for k, vs in dow_buckets.items()
        }
        self._month_index = {
            k: (statistics.mean(vs) / overall if overall else 1.0)
            for k, vs in month_buckets.items()
        }

    def _try_fit_prophet(self, dates: list[datetime], values: list[float]) -> None:
        try:
            import pandas as pd  # lazy
            from prophet import Prophet  # lazy
        except Exception:  # pragma: no cover - optional heavy dependency
            self._prophet_model = None
            return
        try:  # pragma: no cover - exercised only when prophet present
            df = pd.DataFrame({"ds": dates, "y": values})
            model = Prophet(
                weekly_seasonality=True, yearly_seasonality=True, daily_seasonality=False
            )
            model.fit(df)
            self._prophet_model = model
        except Exception as exc:  # pragma: no cover
            _log.warning("prophet_fit_failed", extra={"error": str(exc)})
            self._prophet_model = None

    def predict_next_n_days(self, n: int = 7) -> list[dict[str, Any]]:
        """Forecast the next ``n`` days. Uses Prophet if fitted, else heuristic."""
        if not self._fitted:
            raise RuntimeError("fit() must be called before predict_next_n_days()")
        if self._prophet_model is not None:  # pragma: no cover - requires prophet

            future = self._prophet_model.make_future_dataframe(periods=n)
            forecast = self._prophet_model.predict(future).tail(n)
            return [
                {"ds": row.ds.to_pydatetime(), "yhat": float(row.yhat)}
                for row in forecast.itertuples()
            ]

        last_date = self._history[-1][0] if self._history else datetime.now()
        from datetime import timedelta

        out: list[dict[str, Any]] = []
        base = statistics.mean([v for _, v in self._history]) if self._history else 0.0
        for i in range(1, n + 1):
            d = last_date + timedelta(days=i)
            out.append({"ds": d, "yhat": base * self.get_seasonal_boost(d)})
        return out

    def get_seasonal_boost(self, target_date: datetime) -> float:
        """Return a seasonal multiplier in [0.5, 2.0]."""
        if not self._fitted:
            return 1.0
        dow = self._dow_index.get(target_date.weekday(), 1.0)
        month = self._month_index.get(target_date.month, 1.0)
        return clamp((dow + month) / 2.0, _BOOST_MIN, _BOOST_MAX)
