"""High-level: services composed over the engine + DB."""
from datetime import date

import pytest

from app.data.cards import get_card
from app.services import recommend, redeem
from app.services.ingest import Ingestor


def test_best_card_ranks_by_value(db):
    db.add_user_card("hdfc_millennia", "Millennia")
    db.add_user_card("axis_ace", "Ace")
    r = recommend.best_card(db, 1000, merchant="amazon")
    assert r["best"]["name"] == "Millennia" and r["best"]["reward_value"] == pytest.approx(50)
    r = recommend.best_card(db, 1000, category="utilities")
    assert r["best"]["name"] == "Ace"


def test_best_card_respects_month_to_date_caps(db, categorizer):
    uid = db.add_user_card("hdfc_millennia", "Millennia")
    db.add_user_card("axis_ace", "Ace")
    ing = Ingestor(db, categorizer)
    ing.add(20000, merchant="amazon", user_card_id=uid, txn_date=date.today().isoformat())  # 5% cap now full
    r = recommend.best_card(db, 1000, merchant="amazon")
    assert r["best"]["name"] == "Ace"  # 1.5% beats Millennia's post-cap 1%


def test_optimizer_splits_across_caps():
    cards = [get_card("hdfc_millennia"), get_card("axis_ace")]
    out = recommend.optimize(cards, {("online_shopping", "amazon"): 40000}, "best")
    split = out["allocation"][0]["cards"]
    assert split["hdfc_millennia"] == pytest.approx(20000, rel=0.15)  # 1000-pt cap at 5% = Rs.20k
    assert split["axis_ace"] > 0


def test_discover_prefers_cards_that_fit_spend(db):
    buckets = {("food_delivery", "swiggy"): 15000}
    d = recommend.discover(db, buckets)
    assert d["recommendations"][0]["card"]["id"] == "hdfc_swiggy"
    assert d["recommendations"][0]["incremental_value"] > 0


def test_missed_savings(db, categorizer):
    a = db.add_user_card("hdfc_millennia", "Millennia")
    b = db.add_user_card("axis_ace", "Ace")
    ing = Ingestor(db, categorizer)
    today = date.today().isoformat()
    ing.add(1000, merchant="amazon", user_card_id=b, txn_date=today)  # wrong card: 1.5% vs 5%
    ing.add(1000, merchant="amazon", user_card_id=a, txn_date=today)  # right card
    m = recommend.missed_savings(db, today[:8] + "01", "2999-01-01")
    assert m["missed"] == pytest.approx(35) and len(m["top_misses"]) == 1


def test_goal_plan_uses_cheapest_source_first(db):
    db.add_user_card("axis_atlas", "Atlas", points_balance=10000)          # 1:1 KrisFlyer, portal 1.0 -> cost 1.0
    db.add_user_card("hdfc_infinia", "Infinia", points_balance=50000)      # 1:1, portal 1.0 -> cost 1.0
    db.add_user_card("hdfc_regalia_gold", "Regalia", points_balance=20000)  # 1:0.5, portal 0.5 -> cost 1.0
    g = redeem.goal_plan(db, "krisflyer", 30000)
    assert g["complete"] and g["achievable"] == 30000
    with pytest.raises(ValueError):
        redeem.goal_plan(db, "nope", 1)


def test_sms_import_matches_card_by_last4(db, categorizer):
    uid = db.add_user_card("hdfc_regalia_gold", "RG", last4="1234")
    r = Ingestor(db, categorizer).import_sms("Rs.500 spent on HDFC Bank Card x1234 at SWIGGY on 2026-09-01\n\nhello")
    assert len(r["imported"]) == 1 and len(r["skipped"]) == 1
    t = r["imported"][0]
    assert t["user_card_id"] == uid and t["merchant"] == "swiggy" and t["category"] == "food_delivery"


def test_redemption_options_sorted(db):
    db.add_user_card("hdfc_infinia", "Inf", points_balance=10000)
    r = redeem.redemption_options(db)
    vals = [o["value"] for o in r["cards"][0]["options"]]
    assert vals == sorted(vals, reverse=True) and r["totals"]["best"] >= r["totals"]["cash"]
