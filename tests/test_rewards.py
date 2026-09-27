"""Low-level: the pure rewards engine."""
import pytest

from app.core.rewards import (MonthState, Txn, apply_earn, candidate_rules, compute_earn, effective_fee,
                              milestone_value, point_value, simulate)
from app.data.cards import CARDS, get_card


def card(i):
    return get_card(i)


def test_catalogue_is_well_formed():
    ids = set()
    for c in CARDS:
        assert c["id"] not in ids
        ids.add(c["id"])
        assert c["base"]["rate"] > 0
        for r in c["rules"]:
            assert r["rate"] > 0 and r["id"] and r["label"]
            assert not ("merchants" in r and "categories" in r)


def test_base_rate():
    e = compute_earn(card("axis_ace"), Txn(1000, "others"))
    assert e.points == pytest.approx(15)  # 1.5%
    assert e.value == pytest.approx(15)


def test_excluded_category_earns_nothing():
    e = compute_earn(card("hdfc_infinia"), Txn(5000, "fuel", "iocl"))
    assert e.excluded and e.points == 0 and e.value == 0


def test_merchant_rule_beats_category_rule():
    c = card("axis_flipkart")
    rules = candidate_rules(c, Txn(100, "fashion", "myntra"))
    assert rules[0]["id"] == "myntra75"
    assert compute_earn(c, Txn(1000, "fashion", "myntra")).points == pytest.approx(75)


def test_cap_overflow_falls_back_to_base():
    c = card("hdfc_millennia")  # 5% partner cap 1000 pts, on_cap base 1%
    st = MonthState()
    e1 = compute_earn(c, Txn(15000, "online_shopping", "amazon"), st)
    apply_earn(st, Txn(15000, "online_shopping", "amazon"), e1)
    assert e1.points == pytest.approx(750)
    e2 = compute_earn(c, Txn(10000, "online_shopping", "amazon"), st)
    # 5000 at 5% fills the remaining 250 cap, remaining 5000 at 1% base
    assert e2.points == pytest.approx(250 + 50)
    assert e2.capped


def test_cap_with_no_fallback():
    c = card("sbi_cashback")  # 5% online, cap 5000, on_cap none
    st = MonthState(spend=100000, points_by_rule={"online5": 5000})
    e = compute_earn(c, Txn(2000, "online_shopping", "amazon"), st)
    assert e.points == 0 and e.capped


def test_capped_base_rate():
    c = card("hdfc_swiggy")  # base 1% capped at 500
    st = MonthState(points_by_rule={"base": 480})
    assert compute_earn(c, Txn(10000, "dining"), st).points == pytest.approx(20)


def test_monthly_threshold_splits_transaction():
    c = card("idfc_wealth")  # 2/100 base, 6.67/100 above Rs.20k monthly
    st = MonthState(spend=15000)
    e = compute_earn(c, Txn(10000, "dining"), st)
    assert e.points == pytest.approx(5000 * 0.02 + 5000 * 0.0667, rel=1e-3)


def test_simulate_is_order_dependent_and_consistent():
    c = card("hdfc_millennia")
    txns = [Txn(10000, "online_shopping", "amazon")] * 3
    earns, st = simulate(c, txns)
    assert [e.points for e in earns] == pytest.approx([500, 500, 100])
    assert st.spend == 30000


def test_point_value_modes():
    atlas = card("axis_atlas")
    assert point_value(atlas, "cash") == 0.2
    assert point_value(atlas, "portal") == 1.0
    assert point_value(atlas, "best") >= point_value(atlas, "portal")


def test_fee_waiver_and_milestones():
    rg = card("hdfc_regalia_gold")
    assert effective_fee(rg, 399999) == 2500
    assert effective_fee(rg, 400000) == 0
    v, hit = milestone_value(card("amex_plat_travel"), 400000, "portal")
    assert len(hit) == 2 and v == pytest.approx((15000 + 25000) * 0.8 + 10000)
