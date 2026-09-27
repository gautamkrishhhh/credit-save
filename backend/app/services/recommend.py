"""Recommendation services.

* best_card        -- which card in my wallet to swipe for this purchase
* missed_savings   -- how much I lost by using a sub-optimal card
* optimize         -- greedy, cap-aware allocation of a spend profile across cards
* discover         -- which new card adds the most value to my wallet
* compare          -- side-by-side card comparison on my spend profile
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from itertools import combinations

from ..core.db import Database
from ..core.rewards import MonthState, Txn, apply_earn, compute_earn, effective_fee, milestone_value
from ..data.cards import CARDS, get_card
from ..data.offers import OFFERS
from ..data.taxonomy import CATEGORIES, merchant_category, merchant_name
from ..ml.forecast import forecast_spend, last_n_months
from .wallet import card_summary, month_bounds, month_states, to_txn, value_mode

# ------------------------------------------------------------------ offers

def offer_discount(card: dict, merchant: str | None, category: str | None, amount: float,
                   on: date | None = None) -> tuple[float, dict | None]:
    best, best_offer = 0.0, None
    on = on or date.today()
    today = on.isoformat()
    for o in OFFERS:
        if o.get("valid_till", "9999") < today:
            continue
        if "weekdays" in o and on.weekday() not in o["weekdays"]:
            continue
        if o.get("merchant") and o["merchant"] != merchant:
            continue
        if not o.get("merchant") and o.get("category") != category:
            continue
        if "cards" in o and card["id"] not in o["cards"]:
            continue
        if "issuers" in o and card["issuer"] not in o["issuers"]:
            continue
        if amount < o.get("min_txn", 0):
            continue
        d = o.get("flat_discount") or 0.0
        if o.get("discount_pct"):
            d = max(d, min(amount * o["discount_pct"] / 100, o.get("max_discount") or 1e12))
        if d > best:
            best, best_offer = d, o
    return round(best, 2), best_offer


# ------------------------------------------------------------------ best card

def best_card(db: Database, amount: float, merchant: str | None = None, category: str | None = None,
              include_catalog: bool = True) -> dict:
    category = category or merchant_category(merchant) or "others"
    mode = value_mode(db)
    txn = Txn(float(amount), category, merchant)
    states = month_states(db)
    ranked = []
    for uc in db.list_user_cards():
        card = get_card(uc["card_id"])
        if not card:
            continue
        e = compute_earn(card, txn, states.get(uc["id"], MonthState()), mode)
        disc, offer = offer_discount(card, merchant, category, amount)
        ranked.append({
            "user_card_id": uc["id"], "card_id": card["id"], "name": uc["nickname"] or card["name"],
            "issuer": card["issuer"], "points": e.points, "currency": card["reward_currency"],
            "reward_value": e.value, "offer_value": disc, "offer": offer,
            "total_value": round(e.value + disc, 2), "effective_pct": round(100 * (e.value + disc) / amount, 2),
            "rule": e.primary_rule, "capped": e.capped, "excluded": e.excluded, "notes": e.notes,
        })
    ranked.sort(key=lambda r: -r["total_value"])

    suggestion = None
    if include_catalog:
        owned = {r["card_id"] for r in ranked}
        best_owned = ranked[0]["total_value"] if ranked else 0.0
        cands = []
        for card in CARDS:
            if card["id"] in owned:
                continue
            e = compute_earn(card, txn, MonthState(), mode)
            disc, _ = offer_discount(card, merchant, category, amount)
            cands.append((e.value + disc, card, e))
        cands.sort(key=lambda c: -c[0])
        if cands and cands[0][0] > best_owned * 1.2 + 1:
            v, card, e = cands[0]
            suggestion = {"card_id": card["id"], "name": card["name"], "total_value": round(v, 2),
                          "effective_pct": round(100 * v / amount, 2), "rule": e.primary_rule,
                          "extra_value": round(v - best_owned, 2)}
    return {
        "amount": amount, "merchant": merchant, "merchant_name": merchant_name(merchant),
        "category": category, "category_name": CATEGORIES.get(category, category), "value_mode": mode,
        "ranked": ranked, "best": ranked[0] if ranked else None, "not_owned_suggestion": suggestion,
    }


# ------------------------------------------------------------------ missed savings

def missed_savings(db: Database, start: str, end: str) -> dict:
    """Chronological replay: for each txn compare the card used vs the best
    wallet card given each card's actual month-to-date state at that moment."""
    mode = value_mode(db)
    ucs = {uc["id"]: uc for uc in db.list_user_cards()}
    txns = sorted([t for t in db.list_transactions(start, end) if not t["is_refund"] and t["user_card_id"] in ucs],
                  key=lambda t: (t["txn_date"], t["id"]))
    states: dict[tuple[int, str], MonthState] = defaultdict(MonthState)
    earned = best_total = 0.0
    items = []
    for t in txns:
        m = t["txn_date"][:7]
        tx = to_txn(t)
        options = []
        for uid, uc in ucs.items():
            card = get_card(uc["card_id"])
            if card:
                options.append((compute_earn(card, tx, states[(uid, m)], mode), uid))
        actual = next(e for e, uid in options if uid == t["user_card_id"])
        best_e, best_uid = max(options, key=lambda o: o[0].value)
        apply_earn(states[(t["user_card_id"], m)], tx, actual)
        earned += actual.value
        best_total += best_e.value
        gap = best_e.value - actual.value
        if gap > 0.5:
            items.append({"txn_id": t["id"], "date": t["txn_date"], "merchant": merchant_name(t["merchant"]) or t["description"],
                          "amount": t["amount"], "used": ucs[t["user_card_id"]]["nickname"] or get_card(ucs[t["user_card_id"]]["card_id"])["name"],
                          "earned": round(actual.value, 2), "better": ucs[best_uid]["nickname"] or get_card(ucs[best_uid]["card_id"])["name"],
                          "could_earn": round(best_e.value, 2), "missed": round(gap, 2)})
    items.sort(key=lambda i: -i["missed"])
    return {"earned": round(earned, 2), "optimal": round(best_total, 2), "missed": round(best_total - earned, 2),
            "efficiency_pct": round(100 * earned / best_total, 1) if best_total else 100.0, "top_misses": items[:10]}


# ------------------------------------------------------------------ spend profile

DEFAULT_PROFILE = {  # typical metro professional, Rs./month
    ("food_delivery", "swiggy"): 4000, ("food_delivery", "zomato"): 2500, ("dining", None): 5000,
    ("grocery", "bigbasket"): 6000, ("online_shopping", "amazon"): 7000, ("online_shopping", "flipkart"): 3000,
    ("fashion", "myntra"): 2500, ("travel_flights", None): 8000, ("travel_hotels", None): 4000,
    ("cabs", "uber"): 3000, ("fuel", None): 4000, ("utilities", None): 3500, ("telecom", "airtel"): 1200,
    ("entertainment", None): 1500, ("health", None): 1500, ("insurance", None): 2500, ("others", None): 4000,
}


def spend_profile(db: Database, months: int = 3, use_forecast: bool = True) -> dict:
    """Average monthly spend per (category, merchant) bucket, optionally
    re-scaled per category by the ML forecast for next month."""
    window = last_n_months(months)
    start = window[0] + "-01"
    end = month_bounds(date.fromisoformat(window[-1] + "-01"))[1]
    # one-off anomalies (a laptop, a gold purchase) aren't recurring spend
    txns = [t for t in db.list_transactions(start, end) if not t["is_refund"] and not t["is_anomaly"]]
    if len(txns) < 10:
        return {"source": "default", "months": 0, "buckets": dict(DEFAULT_PROFILE)}
    active = sorted({t["txn_date"][:7] for t in txns})
    n = max(1, len(active))
    buckets: dict[tuple[str, str | None], float] = defaultdict(float)
    for t in txns:
        buckets[(t["category"], t["merchant"])] += t["amount"] / n
    source = "history"
    if use_forecast:
        fc = forecast_spend(db.list_transactions(), history_months=6)["categories"]
        cat_tot = defaultdict(float)
        for (c, _), v in buckets.items():
            cat_tot[c] += v
        for (c, m), v in list(buckets.items()):
            if c in fc and cat_tot[c] > 0:
                buckets[(c, m)] = v * (fc[c]["point"] / cat_tot[c]) if fc[c]["method"] == "holt" else v
        source = "forecast"
    return {"source": source, "months": n, "buckets": {k: round(v, 2) for k, v in buckets.items() if v > 0}}


# ------------------------------------------------------------------ optimizer

def optimize(cards: list[dict], buckets: dict, mode: str = "best", months: int = 12) -> dict:
    """Allocate a monthly spend profile across cards to maximise reward value.

    Greedy with cap-awareness: spend is cut into chunks; buckets whose best
    marginal rate is highest are served first (so scarce capped accelerators
    go to the spend that benefits most); each chunk goes to the card with the
    highest marginal value given that card's running month state. Annualised
    with milestones and fees (a card only 'costs' its fee if it's used)."""
    if not cards:
        return {"monthly_value": 0.0, "annual_net": 0.0, "per_card": {}, "allocation": []}
    states = {c["id"]: MonthState() for c in cards}

    def best_rate(key):
        cat, merch = key
        return max(compute_earn(c, Txn(100.0, cat, merch), MonthState(), mode).value for c in cards)

    order = sorted(buckets.items(), key=lambda kv: -best_rate(kv[0]))
    alloc = []
    monthly = 0.0
    per_card_spend = defaultdict(float)
    per_card_value = defaultdict(float)
    for (cat, merch), amount in order:
        n_chunks = max(1, min(10, int(amount // 500)))
        chunk = amount / n_chunks
        split = defaultdict(float)
        for _ in range(n_chunks):
            tx = Txn(chunk, cat, merch)
            best = max(((compute_earn(c, tx, states[c["id"]], mode), c) for c in cards), key=lambda ec: ec[0].value)
            e, c = best
            apply_earn(states[c["id"]], tx, e)
            split[c["id"]] += chunk
            monthly += e.value
            per_card_spend[c["id"]] += chunk
            per_card_value[c["id"]] += e.value
        alloc.append({"category": cat, "merchant": merch, "amount": round(amount, 2),
                      "cards": {k: round(v, 2) for k, v in split.items()}})

    per_card = {}
    annual_net = 0.0
    for c in cards:
        annual_spend = per_card_spend[c["id"]] * months
        rewards = per_card_value[c["id"]] * months
        ms_val, ms_hit = milestone_value(c, annual_spend, mode)
        fee = effective_fee(c, annual_spend)
        net = rewards + ms_val - fee
        per_card[c["id"]] = {"name": c["name"], "annual_spend": round(annual_spend), "rewards": round(rewards),
                             "milestones": round(ms_val), "milestones_hit": ms_hit, "fee": fee, "net": round(net)}
        annual_net += net
    return {"monthly_value": round(monthly, 2), "annual_net": round(annual_net, 2), "per_card": per_card, "allocation": alloc}


def discover(db: Database, buckets: dict | None = None, income_lpa: float | None = None, top: int = 8) -> dict:
    mode = value_mode(db)
    prof = {"source": "custom", "buckets": buckets} if buckets else spend_profile(db)
    buckets = prof["buckets"]
    owned_ids = [uc["card_id"] for uc in db.list_user_cards()]
    owned = [get_card(i) for i in dict.fromkeys(owned_ids) if get_card(i)]
    base = optimize(owned, buckets, mode)
    results = []
    for card in CARDS:
        if card["id"] in owned_ids:
            continue
        if income_lpa is not None and card.get("min_income_lpa", 0) > income_lpa:
            continue
        with_card = optimize(owned + [card], buckets, mode)
        alone = optimize([card], buckets, mode)
        pc = with_card["per_card"][card["id"]]
        gain = with_card["annual_net"] - base["annual_net"]
        results.append({
            "card": card_summary(card, mode), "incremental_value": round(gain), "standalone_net": round(alone["annual_net"]),
            "spend_routed": pc["annual_spend"], "rewards": pc["rewards"], "milestones": pc["milestones"], "fee": pc["fee"],
            "why": _why(card, with_card, buckets),
        })
    results.sort(key=lambda r: -r["incremental_value"])

    # best 2-card combination from scratch (useful if starting fresh)
    pool = sorted(results, key=lambda r: -r["standalone_net"])[:10]
    pool_cards = [get_card(r["card"]["id"]) for r in pool] + owned
    best_pair = None
    for a, b in combinations(pool_cards, 2):
        v = optimize([a, b], buckets, mode)["annual_net"]
        if best_pair is None or v > best_pair["annual_net"]:
            best_pair = {"cards": [a["name"], b["name"]], "ids": [a["id"], b["id"]], "annual_net": round(v)}

    monthly_total = sum(buckets.values())
    return {
        "profile_source": prof["source"], "monthly_spend": round(monthly_total), "value_mode": mode,
        "profile": _profile_by_category(buckets),
        "current_wallet_net": round(base["annual_net"]), "current_per_card": base["per_card"],
        "recommendations": results[:top], "best_pair": best_pair,
    }


def _profile_by_category(buckets: dict) -> list[dict]:
    agg = defaultdict(float)
    for (c, _), v in buckets.items():
        agg[c] += v
    return sorted([{"category": c, "name": CATEGORIES.get(c, c), "monthly": round(v)} for c, v in agg.items()],
                  key=lambda r: -r["monthly"])


def _why(card: dict, result: dict, buckets: dict) -> list[str]:
    reasons = []
    by_cat = defaultdict(float)
    for a in result["allocation"]:
        amt = a["cards"].get(card["id"], 0.0)
        if amt:
            by_cat[CATEGORIES.get(a["category"], a["category"])] += amt
    for cat, amt in sorted(by_cat.items(), key=lambda kv: -kv[1])[:3]:
        reasons.append(f"Best card for ₹{amt:,.0f}/mo of {cat.lower()}")
    pc = result["per_card"][card["id"]]
    if pc["milestones"]:
        reasons.append(f"Unlocks ₹{pc['milestones']:,} in milestone benefits")
    if card.get("annual_fee") and pc["fee"] == 0:
        reasons.append("Annual fee waived at your spend level")
    return reasons


def compare(db: Database, card_ids: list[str]) -> dict:
    mode = value_mode(db)
    cards = [get_card(i) for i in card_ids if get_card(i)]
    buckets = spend_profile(db)["buckets"]
    cats = list(CATEGORIES)
    grid = []
    for cat in cats:
        row = {"category": cat, "name": CATEGORIES[cat]}
        for c in cards:
            row[c["id"]] = round(compute_earn(c, Txn(1000.0, cat, None), MonthState(), mode).value / 10, 2)
        grid.append(row)
    summaries = []
    for c in cards:
        r = optimize([c], buckets, mode)
        summaries.append({**card_summary(c, mode), "annual_net_on_profile": round(r["annual_net"]),
                          "per_card": r["per_card"][c["id"]]})
    return {"cards": summaries, "return_by_category_pct": grid, "value_mode": mode}
