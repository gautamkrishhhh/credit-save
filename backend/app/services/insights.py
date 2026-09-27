"""Dashboard + insights: aggregates every engine into one view."""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from ..core.db import Database
from ..data.taxonomy import CATEGORIES, merchant_name
from ..ml.anomaly import score_transactions
from ..ml.forecast import forecast_spend, last_n_months
from .recommend import best_card, missed_savings
from .redeem import milestones, redemption_options
from .wallet import month_bounds, wallet


def dashboard(db: Database) -> dict:
    w = wallet(db)
    start, end = month_bounds()
    month_txns = [t for t in db.list_transactions(start, end) if not t["is_refund"]]
    by_cat = defaultdict(float)
    for t in month_txns:
        by_cat[t["category"]] += t["amount"]
    trend = []
    for m in last_n_months(6, include_current=True):
        s, e = month_bounds(date.fromisoformat(m + "-01"))
        trend.append({"month": m, "spend": round(sum(t["amount"] for t in db.list_transactions(s, e) if not t["is_refund"]))})
    ms = missed_savings(db, start, end)
    ytd = missed_savings(db, f"{date.today().year}-01-01", end)
    red = redemption_options(db)
    upcoming = []
    for card in milestones(db):
        for m in card["milestones"]:
            if not m["achieved"]:
                upcoming.append({"card": card["name"], **m})
    upcoming.sort(key=lambda m: -m["pct"])
    return {
        "cards": len(w),
        "points_value": red["totals"],
        "month": {"spend": round(sum(by_cat.values())), "rewards": round(sum(c["month_value"] for c in w)),
                  "txns": len(month_txns), "missed": ms["missed"], "efficiency_pct": ms["efficiency_pct"]},
        "ytd": {"rewards": ytd["earned"], "missed": ytd["missed"], "efficiency_pct": ytd["efficiency_pct"]},
        "by_category": sorted([{"category": c, "name": CATEGORIES.get(c, c), "amount": round(v)} for c, v in by_cat.items()],
                              key=lambda r: -r["amount"]),
        "trend": trend,
        "wallet": w,
        "expiring": [c for c in red["cards"] if c["expiring"]],
        "upcoming_milestones": upcoming[:5],
        "top_misses": ms["top_misses"][:5],
        "recent": db.list_transactions(limit=8),
    }


def insights(db: Database) -> dict:
    txns = db.list_transactions()
    fc = forecast_spend(txns)
    anomalies = [t for t in db.list_transactions() if t["is_anomaly"]]
    reasons = {s["id"]: s["reason"] for s in score_transactions([t for t in txns if not t["is_refund"]])}
    tips = []
    # tip 1: biggest forecast categories -> best card for them
    cats = sorted(fc["categories"].items(), key=lambda kv: -kv[1]["point"])[:4]
    for cat, f in cats:
        if f["point"] < 500 or cat in ("rent", "government", "wallet_load", "insurance"):
            continue
        bc = best_card(db, f["point"], None, cat, include_catalog=True)
        if bc["best"]:
            tip = (f"You'll likely spend ~₹{f['point']:,.0f} on {CATEGORIES[cat].lower()} next month. "
                   f"Use {bc['best']['name']} ({bc['best']['effective_pct']}% back).")
            if bc["not_owned_suggestion"]:
                s = bc["not_owned_suggestion"]
                tip += f" {s['name']} would return {s['effective_pct']}%."
            tips.append({"category": cat, "text": tip})
        if f["trend"] > 0.1 * max(f["point"], 1):
            tips.append({"category": cat, "text": f"{CATEGORIES[cat]} spend is trending up (+₹{f['trend']:,.0f}/month)."})
    red = redemption_options(db)
    for c in red["cards"]:
        if c["expiring"]:
            tips.append({"category": "points", "text": f"{c['balance']:,.0f} {c['currency']} on {c['name']} expire in {c['expiring']['days']} days — best use: {c['best']['type']} (₹{c['best']['value']:,.0f})."})
        elif c["uplift_vs_worst"] > 1000:
            tips.append({"category": "points", "text": f"Redeeming {c['name']} points via {c['best']['type']} is worth ₹{c['uplift_vs_worst']:,.0f} more than the worst option."})
    top_merchants = defaultdict(float)
    for t in txns:
        if not t["is_refund"]:
            top_merchants[merchant_name(t["merchant"]) or (t["description"] or "Other")] += t["amount"]
    return {
        "forecast": fc,
        "anomalies": [{**t, "reason": reasons.get(t["id"])} for t in anomalies][:20],
        "tips": tips,
        "top_merchants": sorted([{"merchant": k, "amount": round(v)} for k, v in top_merchants.items()], key=lambda r: -r["amount"])[:10],
    }
