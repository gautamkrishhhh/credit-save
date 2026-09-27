"""Monthly spend forecasting per category.

Holt's linear exponential smoothing (level + trend), implemented directly in
numpy. The smoothing parameters (alpha, beta) are fitted per series by grid
search minimising one-step-ahead squared error. Prediction intervals come from
the in-sample residual standard deviation. Short series (< 3 months) fall
back to the mean.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

import numpy as np

_GRID = np.linspace(0.05, 0.95, 19)


@dataclass
class Forecast:
    point: float
    lower: float
    upper: float
    method: str
    alpha: float | None = None
    beta: float | None = None
    trend: float = 0.0


def _holt_sse(y: np.ndarray, a: float, b: float) -> tuple[float, float, float, np.ndarray]:
    level, trend = y[0], (y[1] - y[0]) if len(y) > 1 else 0.0
    errs = np.empty(len(y) - 1)
    for t in range(1, len(y)):
        pred = level + trend
        errs[t - 1] = y[t] - pred
        new_level = a * y[t] + (1 - a) * pred
        trend = b * (new_level - level) + (1 - b) * trend
        level = new_level
    return float(np.sum(errs ** 2)), level, trend, errs


def holt_forecast(series: list[float]) -> Forecast:
    y = np.asarray(series, dtype=float)
    if len(y) == 0:
        return Forecast(0.0, 0.0, 0.0, "empty")
    if len(y) < 3:
        m = float(y.mean())
        return Forecast(m, m * 0.7, m * 1.3, "mean")
    best = None
    for a in _GRID:
        for b in _GRID:
            sse, level, trend, errs = _holt_sse(y, a, b)
            if best is None or sse < best[0]:
                best = (sse, a, b, level, trend, errs)
    _, a, b, level, trend, errs = best
    point = max(0.0, level + trend)
    sd = float(np.std(errs, ddof=1)) if len(errs) > 1 else point * 0.2
    return Forecast(round(point, 2), round(max(0.0, point - 1.28 * sd), 2), round(point + 1.28 * sd, 2),
                    "holt", round(float(a), 2), round(float(b), 2), round(float(trend), 2))


def month_key(d: str) -> str:
    return d[:7]


def monthly_matrix(txns: list[dict], months: list[str]) -> dict[str, list[float]]:
    agg: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for t in txns:
        if t.get("is_refund"):
            continue
        agg[t["category"]][month_key(t["txn_date"])] += t["amount"]
    return {c: [round(v.get(m, 0.0), 2) for m in months] for c, v in agg.items()}


def last_n_months(n: int, today: date | None = None, include_current: bool = False) -> list[str]:
    today = today or date.today()
    y, m = today.year, today.month
    out = []
    if not include_current:
        m -= 1
    for _ in range(n):
        if m == 0:
            y, m = y - 1, 12
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
    return list(reversed(out))


def forecast_spend(txns: list[dict], history_months: int = 6, today: date | None = None) -> dict:
    months = last_n_months(history_months, today)
    mat = monthly_matrix(txns, months)
    # drop leading months before the user started tracking
    first = next((i for i, m in enumerate(months) if any(mat[c][i] for c in mat)), len(months))
    months = months[first:]
    out = {}
    for cat, series in mat.items():
        s = series[first:]
        if not any(s):
            continue
        f = holt_forecast(s)
        out[cat] = {"history": s, **f.__dict__}
    total = holt_forecast([sum(mat[c][first + i] for c in mat) for i in range(len(months))]) if months else Forecast(0, 0, 0, "empty")
    return {"months": months, "categories": out, "total": total.__dict__}
