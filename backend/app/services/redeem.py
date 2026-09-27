"""Points valuation, redemption options, goal planning and milestones."""
from __future__ import annotations

from datetime import date, timedelta

from ..core.db import Database
from ..core.rewards import effective_fee, point_value
from ..data.cards import get_card
from ..data.partners import PARTNERS
from .wallet import value_mode


def redemption_options(db: Database) -> dict:
    cards = []
    grand = {"cash": 0.0, "portal": 0.0, "best": 0.0}
    for uc in db.list_user_cards():
        card = get_card(uc["card_id"])
        if not card:
            continue
        bal = uc["points_balance"]
        opts = []
        pv = card["point_value"]
        if pv["cash"]:
            opts.append({"type": "Statement credit / cashback", "per_point": pv["cash"], "value": round(bal * pv["cash"], 2)})
        opts.append({"type": "Travel portal / catalogue", "per_point": pv["portal"], "value": round(bal * pv["portal"], 2)})
        for pid, ratio in card.get("transfer", {}).items():
            p = PARTNERS[pid]
            opts.append({"type": f"Transfer to {p['name']}", "partner": pid, "ratio": ratio,
                         "partner_points": round(bal * ratio), "per_point": round(ratio * p["value_inr"], 3),
                         "value": round(bal * ratio * p["value_inr"], 2)})
        opts.sort(key=lambda o: -o["value"])
        worst = min(o["per_point"] for o in opts) or 0.0
        best = opts[0]
        for k in grand:
            grand[k] += bal * point_value(card, k)
        expiring = None
        if uc.get("points_expiry"):
            days = (date.fromisoformat(uc["points_expiry"]) - date.today()).days
            if days <= 90:
                expiring = {"date": uc["points_expiry"], "days": days}
        cards.append({"user_card_id": uc["id"], "name": uc["nickname"] or card["name"], "card_id": card["id"],
                      "currency": card["reward_currency"], "balance": bal, "options": opts, "best": best,
                      "uplift_vs_worst": round(bal * (best["per_point"] - worst), 2), "expiring": expiring})
    return {"cards": cards, "totals": {k: round(v, 2) for k, v in grand.items()}, "value_mode": value_mode(db)}


def goal_plan(db: Database, partner: str, target_points: float) -> dict:
    """Which of my card balances to transfer (cheapest first) to reach
    `target_points` in a partner programme."""
    if partner not in PARTNERS:
        raise ValueError(f"unknown partner {partner}")
    sources = []
    for uc in db.list_user_cards():
        card = get_card(uc["card_id"])
        ratio = (card or {}).get("transfer", {}).get(partner)
        if ratio and uc["points_balance"] > 0:
            # opportunity cost: what each partner point costs in rupees of the card's next-best use
            alt = max(card["point_value"]["portal"], card["point_value"]["cash"])
            sources.append({"uc": uc, "card": card, "ratio": ratio, "cost_per_partner_point": alt / ratio})
    sources.sort(key=lambda s: s["cost_per_partner_point"])
    need = float(target_points)
    plan, got = [], 0.0
    for s in sources:
        if got >= need:
            break
        avail = s["uc"]["points_balance"] * s["ratio"]
        take = min(avail, need - got)
        card_pts = take / s["ratio"]
        plan.append({"card": s["uc"]["nickname"] or s["card"]["name"], "transfer_card_points": round(card_pts),
                     "ratio": f"1 : {s['ratio']:g}", "partner_points": round(take),
                     "opportunity_cost_inr": round(card_pts * s["cost_per_partner_point"] * s["ratio"], 2)})
        got += take
    p = PARTNERS[partner]
    return {"partner": partner, "partner_name": p["name"], "target": target_points, "achievable": round(got),
            "complete": got >= need - 0.5, "shortfall": round(max(0.0, need - got)),
            "estimated_value_inr": round(got * p["value_inr"], 2), "steps": plan}


def milestones(db: Database) -> list[dict]:
    out = []
    start = (date.today() - timedelta(days=365)).isoformat()
    months_elapsed = 12
    mode = value_mode(db)
    for uc in db.list_user_cards():
        card = get_card(uc["card_id"])
        if not card:
            continue
        txns = [t for t in db.list_transactions(start, None, uc["id"]) if not t["is_refund"]]
        spend = sum(t["amount"] for t in txns)
        active_months = len({t["txn_date"][:7] for t in txns}) or 1
        run_rate = spend / min(months_elapsed, active_months) * 12
        items = []
        if card.get("fee_waiver_spend"):
            items.append(_ms("Annual fee waiver", card["fee_waiver_spend"], spend, run_rate, card["annual_fee"]))
        for m in card.get("milestones", []):
            items.append(_ms(m["label"], m["annual_spend"], spend, run_rate,
                             m.get("points", 0) * point_value(card, mode) + m.get("voucher_inr", 0)))
        if items:
            out.append({"user_card_id": uc["id"], "name": uc["nickname"] or card["name"], "spend_12m": round(spend),
                        "projected_annual": round(run_rate), "fee": card["annual_fee"],
                        "fee_payable": effective_fee(card, run_rate), "milestones": items})
    return out


def _ms(label, target, spend, run_rate, reward_value):
    remaining = max(0.0, target - spend)
    return {"label": label, "target": target, "progress": round(spend), "pct": round(min(100.0, 100 * spend / target), 1),
            "remaining": round(remaining), "achieved": remaining == 0, "on_track": run_rate >= target,
            "reward_value": round(reward_value), "monthly_needed": round(remaining / 3) if remaining else 0}
