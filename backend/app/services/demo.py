"""Deterministic demo data: a realistic wallet and ~6 months of spending
(with a growth trend, recurring bills, sub-optimal card choices and a couple
of genuine outliers) so every screen has something meaningful to show."""
from __future__ import annotations

import random
from datetime import date, timedelta

from ..core.db import Database
from ..data.taxonomy import MERCHANTS
from .ingest import Ingestor

WALLET = [
    ("hdfc_regalia_gold", "Regalia Gold", "1234", 42000, 60),
    ("axis_atlas", "Atlas", "5678", 18500, None),
    ("sbi_cashback", "SBI Cashback", "3456", 0, None),
    ("icici_amazon_pay", "Amazon Pay ICICI", "9012", 0, None),
]

# (merchant id or None, description for unknown merchants, category override, monthly freq, amount range)
PATTERNS = [
    ("swiggy", None, None, 8, (250, 900)),
    ("zomato", None, None, 5, (300, 1100)),
    ("bigbasket", None, None, 3, (900, 3500)),
    ("blinkit", None, None, 4, (200, 800)),
    ("amazon", None, None, 3, (500, 6000)),
    ("flipkart", None, None, 1, (800, 4000)),
    ("myntra", None, None, 1, (1200, 3500)),
    ("uber", None, None, 7, (150, 650)),
    (None, "HP PETROL PUMP KORAMANGALA", "fuel", 2, (1500, 3000)),
    ("airtel", None, None, 1, (999, 999)),
    ("bescom", None, None, 1, (1800, 3200)),
    ("netflix", None, None, 1, (649, 649)),
    (None, "THIRD WAVE COFFEE ROASTERS", None, 4, (300, 700)),
    (None, "MEGHANA FOODS RESTAURANT", None, 2, (900, 2500)),
    ("apollo", None, None, 1, (300, 1500)),
    ("makemytrip", None, None, 0.5, (4500, 14000)),
    ("marriott", None, None, 0.3, (7000, 16000)),
    ("bookmyshow", None, None, 1, (500, 1200)),
    (None, "LIC PREMIUM", "insurance", 0.2, (12000, 12000)),
]

# card preference (index into WALLET) -- deliberately imperfect, like real life
HABIT = {"swiggy": 0, "zomato": 2, "amazon": 3, "flipkart": 2, "myntra": 2, "uber": 0, "makemytrip": 0,
         "marriott": 1, "bigbasket": 0, "blinkit": 2, "airtel": 0, "bescom": 0, "netflix": 2}


def seed_demo(db: Database, ingestor: Ingestor, months: int = 6, seed: int = 42) -> dict:
    db.reset()
    rng = random.Random(seed)
    ids = []
    for card_id, nick, last4, pts, exp_days in WALLET:
        exp = (date.today() + timedelta(days=exp_days)).isoformat() if exp_days else None
        ids.append(db.add_user_card(card_id, nick, last4, pts, exp, 300000, 15))
    today = date.today()
    first = (today.replace(day=1) - timedelta(days=31 * (months - 1))).replace(day=1)
    n = 0
    d = first
    month_idx = 0
    while d <= today:
        growth = 1 + 0.06 * month_idx
        days_in_month = ((d.replace(day=28) + timedelta(days=4)).replace(day=1) - d).days
        for mid, desc, cat, freq, (lo, hi) in PATTERNS:
            k = int(freq) + (1 if rng.random() < freq - int(freq) else 0)
            for _ in range(k):
                day = rng.randint(1, days_in_month)
                td = d.replace(day=day)
                if td > today:
                    continue
                amt = round(rng.uniform(lo, hi) * (growth if lo != hi else 1), 0)
                card_idx = HABIT.get(mid, rng.randrange(len(ids)))
                if rng.random() < 0.2:
                    card_idx = rng.randrange(len(ids))
                ingestor.add(amt, description=desc or MERCHANTS[mid][0].upper(), merchant=mid, category=cat,
                             user_card_id=ids[card_idx], txn_date=td.isoformat(), source="demo", rescore=False)
                n += 1
        d = (d + timedelta(days=32)).replace(day=1)
        month_idx += 1
    # genuine outliers
    for amt, desc, mid, back in [(64999, "CROMA ELECTRONICS", "croma", 20), (18500, "TANISHQ", "tanishq", 45)]:
        td = today - timedelta(days=back)
        ingestor.add(amt, description=desc, merchant=mid, user_card_id=ids[0], txn_date=td.isoformat(), source="demo", rescore=False)
        n += 1
    flagged = ingestor.rescore_anomalies()
    db.add_goal("Business class to Singapore", "krisflyer", 60000)
    return {"cards": len(ids), "transactions": n, "anomalies": flagged}
