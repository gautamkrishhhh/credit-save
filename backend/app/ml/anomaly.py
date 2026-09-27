"""Unusual-transaction detection.

With enough history (>= 30 txns) an IsolationForest scores each transaction
on engineered features; with less, a robust per-category z-score (median/MAD)
is used. Both return a score in [0, 1] (higher = more unusual) and a reason.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import date

import numpy as np
from sklearn.ensemble import IsolationForest

from ..data.taxonomy import CATEGORIES

_CAT_IDX = {c: i for i, c in enumerate(CATEGORIES)}
MIN_FOR_FOREST = 30


def _robust_z(x: float, values: list[float]) -> float:
    if len(values) < 3:
        return 0.0
    arr = np.log1p(np.array(values))
    med = float(np.median(arr))
    mad = float(np.median(np.abs(arr - med))) or 0.25
    return (math.log1p(x) - med) / (1.4826 * mad)


def _features(txns: list[dict]) -> np.ndarray:
    merch_freq = Counter((t.get("merchant") or t.get("description") or "").lower() for t in txns)
    by_cat = defaultdict(list)
    for t in txns:
        by_cat[t["category"]].append(t["amount"])
    cat_med = {c: float(np.median(v)) for c, v in by_cat.items()}
    rows = []
    for t in txns:
        d = date.fromisoformat(t["txn_date"][:10])
        key = (t.get("merchant") or t.get("description") or "").lower()
        rows.append([
            math.log1p(t["amount"]),
            math.log1p(t["amount"]) - math.log1p(cat_med[t["category"]]),
            _CAT_IDX.get(t["category"], 0) / len(_CAT_IDX),
            d.weekday() / 6.0,
            1.0 / merch_freq[key],       # rare merchants are more suspicious
            len(by_cat[t["category"]]) / len(txns),  # rare categories too
        ])
    return np.array(rows)


def score_transactions(txns: list[dict]) -> list[dict]:
    """Returns [{"id", "score", "is_anomaly", "reason"}] aligned with txns."""
    if not txns:
        return []
    by_cat = defaultdict(list)
    for t in txns:
        by_cat[t["category"]].append(t["amount"])

    forest_scores = None
    if len(txns) >= MIN_FOR_FOREST:
        X = _features(txns)
        forest = IsolationForest(n_estimators=200, contamination=0.04, random_state=42).fit(X)
        raw = -forest.score_samples(X)  # higher = more anomalous
        lo, hi = float(raw.min()), float(raw.max())
        forest_scores = (raw - lo) / (hi - lo + 1e-9)
        flags = forest.predict(X) == -1

    all_amounts = [t["amount"] for t in txns]
    out = []
    for i, t in enumerate(txns):
        z = _robust_z(t["amount"], by_cat[t["category"]])
        gz = _robust_z(t["amount"], all_amounts)
        if forest_scores is not None:
            score = float(forest_scores[i])
            flag = bool(flags[i]) and z > 3.0  # must also be large for its category
        else:
            score = float(min(1.0, max(0.0, z / 6)))
            flag = z > 3.5
        # a big-ticket purchase in a category you rarely use has no category baseline:
        # judge it against your overall spending instead
        n_cat = len(by_cat[t["category"]])
        rare = n_cat < 3
        if (n_cat == 1 and gz > 3.0) or (n_cat == 2 and gz > 5.0):
            flag, score = True, max(score, min(1.0, gz / 6))
        reason = None
        if flag and rare:
            med = float(np.median(all_amounts))
            reason = (f"₹{t['amount']:,.0f} in a category you rarely use — {t['amount'] / med:.0f}x your median "
                      f"transaction (₹{med:,.0f})")
        elif flag:
            med = float(np.median(by_cat[t["category"]]))
            reason = (f"₹{t['amount']:,.0f} is {t['amount'] / med:.1f}x your typical "
                      f"{CATEGORIES.get(t['category'], t['category']).lower()} spend (₹{med:,.0f})")
        out.append({"id": t.get("id"), "score": round(score, 3), "is_anomaly": flag, "reason": reason})
    return out
