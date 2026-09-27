"""Mid-level: ML + NLP components."""
from datetime import date

import pytest

from app.ml.anomaly import score_transactions
from app.ml.categorizer import Categorizer, normalize, resolve_merchant
from app.ml.forecast import forecast_spend, holt_forecast
from app.ml.nlu import extract
from app.ml.sms_parser import parse_sms, split_messages


@pytest.mark.parametrize("text,mid", [
    ("POS 4411 SWIGGY*BLR", "swiggy"), ("UPI/zomato/40912", "zomato"), ("AMAZON PAY IN ECOM", "amazon"),
    ("Bundl Technologies Bangalore", "swiggy"), ("IOCL FUEL STN 22", "iocl"), ("random words", None),
])
def test_resolve_merchant(text, mid):
    assert resolve_merchant(text) == mid


def test_normalize_strips_ref_numbers():
    assert normalize("POS 123456 SWIGGY*BLR") == "pos swiggy blr"


@pytest.mark.parametrize("text,cat", [
    ("SRI SAI MEDICALS", "health"), ("Hotel Annapurna Residency", "travel_hotels"), ("Kalpana Jewellers", "jewellery"),
    ("Madhav Auto Fuels", "fuel"), ("Priya Boutique", "fashion"), ("RAPIDO BIKE", "cabs"), ("Excel Coaching Classes", "education"),
])
def test_model_generalises_to_unseen_merchants(categorizer, text, cat):
    p = categorizer.predict(text)
    assert p.method == "model" and p.category == cat, p


def test_user_feedback_is_learned():
    c = Categorizer()
    c.train(evaluate=False)
    assert c.predict("ZZQX ENTERPRISES").category != "education"
    c.train(feedback=[{"text": "ZZQX ENTERPRISES", "category": "education"}], evaluate=False)
    assert c.predict("ZZQX ENTERPRISES").category == "education"


def test_categorizer_honest_metrics():
    m = Categorizer().train()
    assert m["unseen_merchant_accuracy"] > 0.6  # grouped split: merchants never seen in training


@pytest.mark.parametrize("sms,amount,last4,merchant,dt", [
    ("Rs.1,250.00 spent on HDFC Bank Card x1234 at SWIGGY on 2026-09-12:20:11:05", 1250.0, "1234", "SWIGGY", "2026-09-12"),
    ("INR 2,499.00 spent using Axis Bank Card XX5678 on 12-09-26 at AMAZON. Avl Limit: INR 1,20,000", 2499.0, "5678", "AMAZON", "2026-09-12"),
    ("Your ICICI Bank Credit Card XX9012 has been used for a transaction of INR 499.00 on Sep 12, 2026 at NETFLIX.", 499.0, "9012", "NETFLIX", "2026-09-12"),
    ("Thank you for using SBI Card ending 3456 for Rs 890 at ZOMATO on 12/09/2026.", 890.0, "3456", "ZOMATO", "2026-09-12"),
])
def test_sms_formats(sms, amount, last4, merchant, dt):
    p = parse_sms(sms)
    assert p.ok and p.amount == amount and p.last4 == last4 and p.merchant_text == merchant and p.txn_date == dt
    assert not p.is_refund


def test_sms_refund_and_noise():
    r = parse_sms("Refund of Rs 499 credited to your card ending 1234 from MYNTRA")
    assert r.ok and r.is_refund and r.merchant_text == "MYNTRA"
    assert not parse_sms("Your OTP is 123456. Do not share.").ok
    assert len(split_messages("Rs 10 spent at A\n\nRs 20 spent at B")) == 2


def test_holt_tracks_linear_trend():
    f = holt_forecast([1000, 1100, 1200, 1300, 1400, 1500])
    assert f.method == "holt" and f.point == pytest.approx(1600, rel=0.03)
    assert f.lower <= f.point <= f.upper


def test_forecast_short_history_uses_mean():
    assert holt_forecast([100, 300]).method == "mean"


def test_forecast_spend_by_category():
    txns = [{"txn_date": f"2026-0{m}-10", "category": "dining", "amount": 1000 * m, "is_refund": 0} for m in range(3, 9)]
    out = forecast_spend(txns, 6, today=date(2026, 9, 15))
    assert out["categories"]["dining"]["point"] == pytest.approx(9000, rel=0.1)


def test_anomaly_flags_outliers_only():
    txns = [{"id": i, "amount": 400 + (i % 7) * 30, "category": "food_delivery", "merchant": "swiggy",
             "description": "", "txn_date": f"2026-08-{i % 28 + 1:02d}"} for i in range(60)]
    txns.append({"id": 999, "amount": 9000, "category": "food_delivery", "merchant": "swiggy", "description": "", "txn_date": "2026-08-15"})
    txns.append({"id": 1000, "amount": 80000, "category": "jewellery", "merchant": "tanishq", "description": "", "txn_date": "2026-08-16"})
    flagged = {s["id"] for s in score_transactions(txns) if s["is_anomaly"]}
    assert {999, 1000} <= flagged and len(flagged) <= 4


@pytest.mark.parametrize("text,field,value", [
    ("which card for swiggy 800", "merchant", "swiggy"),
    ("best card for 5k on amazon", "amount", 5000),
    ("spending 1.2 lakh on flights", "amount", 120000),
    ("spending 1.2 lakh on flights", "category", "travel_flights"),
    ("compare atlas vs infinia", "cards", ["axis_atlas", "hdfc_infinia"]),
    ("tell me about flipkart axis", "merchant", None),  # card name, not the merchant
    ("amazn 5000", "merchant", "amazon"),  # fuzzy typo
    ("i need 60000 krisflyer miles", "partner", "krisflyer"),
])
def test_entity_extraction(text, field, value):
    assert getattr(extract(text), field) == value


# hand-written paraphrases never seen in training -> honest intent accuracy
HELD_OUT = [
    ("what's the best card to use at zomato", "best_card"), ("ordering from blinkit for 1200, which card", "best_card"),
    ("which card gives max return on petrol", "best_card"), ("what are all my points worth in rupees", "points_value"),
    ("best way to spend my regalia points", "redeem"), ("i want to get a new credit card", "discover"),
    ("infinia or magnus which is better", "compare"), ("what perks does magnus have", "card_info"),
    ("how much have i spent on food this month", "spend_summary"), ("how much money did i lose on rewards", "missed"),
    ("am i close to my fee waiver", "milestones"), ("are there discounts on flipkart", "offers"),
    ("what will my expenses be next month", "forecast"), ("any weird charges on my cards", "anomaly"),
    ("hello sage", "greeting"), ("what can you help me with", "help"), ("thank you so much", "thanks"),
    ("how do i collect 40000 avios", "goal"), ("which card should i swipe for my electricity bill", "best_card"),
    ("should i apply for axis atlas", "discover"),
]


def test_intent_classifier_held_out(intents):
    correct = sum(intents.predict(t)[0] == y for t, y in HELD_OUT)
    assert correct / len(HELD_OUT) >= 0.8, [(t, intents.predict(t)[0]) for t, y in HELD_OUT if intents.predict(t)[0] != y]
