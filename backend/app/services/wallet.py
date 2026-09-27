"""Wallet service: joins the user's cards with the catalogue and rebuilds each
card's month-to-date rewards state by replaying this month's transactions
through the rewards engine (so caps/thresholds are always exact)."""
from __future__ import annotations

from datetime import date, timedelta

from ..core.db import Database
from ..core.rewards import MonthState, Txn, apply_earn, compute_earn, point_value
from ..data.cards import get_card


def month_bounds(d: date | None = None) -> tuple[str, str]:
    d = d or date.today()
    start = d.replace(day=1)
    nxt = (start + timedelta(days=32)).replace(day=1)
    return start.isoformat(), nxt.isoformat()


def value_mode(db: Database) -> str:
    return db.get_setting("value_mode", "best") or "best"


def to_txn(t: dict) -> Txn:
    return Txn(float(t["amount"]), t["category"], t.get("merchant"))


def month_states(db: Database, d: date | None = None) -> dict[int, MonthState]:
    start, end = month_bounds(d)
    states: dict[int, MonthState] = {uc["id"]: MonthState() for uc in db.list_user_cards()}
    ucs = {uc["id"]: uc for uc in db.list_user_cards()}
    txns = [t for t in db.list_transactions(start, end) if t["user_card_id"] in ucs and not t["is_refund"]]
    txns.sort(key=lambda t: (t["txn_date"], t["id"]))
    for t in txns:
        card = get_card(ucs[t["user_card_id"]]["card_id"])
        if not card:
            continue
        st = states[t["user_card_id"]]
        apply_earn(st, to_txn(t), compute_earn(card, to_txn(t), st))
    return states


def wallet(db: Database) -> list[dict]:
    mode = value_mode(db)
    states = month_states(db)
    year_ago = (date.today() - timedelta(days=365)).isoformat()
    out = []
    for uc in db.list_user_cards():
        card = get_card(uc["card_id"])
        if not card:
            continue
        st = states.get(uc["id"], MonthState())
        spend_12m = sum(t["amount"] for t in db.list_transactions(year_ago, None, uc["id"]) if not t["is_refund"])
        pv = point_value(card, mode)
        caps = []
        for r in card.get("rules", []) + [{"id": "base", "label": "Base rate", **card["base"]}]:
            if r.get("cap"):
                used = st.points_by_rule.get(r["id"], 0.0)
                caps.append({"rule": r["label"], "used": round(used, 1), "cap": r["cap"],
                             "pct": round(100 * used / r["cap"], 1)})
        out.append({
            **uc,
            "card": card_summary(card, mode),
            "display_name": uc["nickname"] or card["name"],
            "points_value": round(uc["points_balance"] * pv, 2),
            "value_per_point": round(pv, 3),
            "month_spend": round(st.spend, 2),
            "month_points": round(sum(st.points_by_rule.values()), 2),
            "month_value": round(sum(st.points_by_rule.values()) * pv, 2),
            "spend_12m": round(spend_12m, 2),
            "caps": caps,
        })
    return out


def card_summary(card: dict, mode: str = "best") -> dict:
    from ..core.rewards import best_transfer
    bt_id, bt_val = best_transfer(card)
    top = max([card["base"]["rate"]] + [r["rate"] for r in card.get("rules", [])])
    return {
        "id": card["id"], "name": card["name"], "issuer": card["issuer"], "network": card["network"],
        "tier": card["tier"], "annual_fee": card["annual_fee"], "fee_waiver_spend": card.get("fee_waiver_spend"),
        "reward_currency": card["reward_currency"], "base_rate": card["base"]["rate"],
        "base_return_pct": round(card["base"]["rate"] * point_value(card, mode), 2),
        "top_return_pct": round(top * point_value(card, mode), 2),
        "value_per_point": round(point_value(card, mode), 3),
        "best_transfer": bt_id, "best_transfer_value": round(bt_val, 3),
        "rules": [{"label": r["label"], "rate": r["rate"], "cap": r.get("cap")} for r in card.get("rules", [])],
        "exclusions": card.get("exclusions", []), "lounge": card.get("lounge"), "forex_markup": card.get("forex_markup"),
        "perks": card.get("perks", []), "milestones": card.get("milestones", []), "min_income_lpa": card.get("min_income_lpa"),
        "transfer": card.get("transfer", {}), "point_value": card["point_value"],
    }
