"""Transaction categorizer.

Two-stage hybrid:
  1. Merchant resolver -- deterministic alias matching (word-boundary, longest
     alias wins). Gives exact merchant ids the rewards engine needs.
  2. ML fallback -- TF-IDF over character n-grams + word n-grams feeding a
     multinomial logistic regression. Trained on a synthetic corpus of noisy
     bank descriptors ("POS 4411 SWIGGY*BLR", "UPI/zomato/40912..."), plus
     every correction the user makes (online learning via retrain).
"""
from __future__ import annotations

import random
import re
import threading
from dataclasses import dataclass

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import FeatureUnion, Pipeline

from ..data.taxonomy import CATEGORIES, MERCHANTS

_WS = re.compile(r"\s+")
_NOISE = re.compile(r"[^a-z0-9.&' ]+")


def normalize(text: str) -> str:
    t = (text or "").lower()
    t = _NOISE.sub(" ", t)
    t = re.sub(r"\b\d{4,}\b", " ", t)  # ref numbers / card digits carry no signal
    return _WS.sub(" ", t).strip()


# ------------------------------------------------------------ merchant resolver

_ALIAS_INDEX: list[tuple[re.Pattern, str, int]] = []
for _mid, (_name, _cat, _aliases) in MERCHANTS.items():
    for _a in set(_aliases + [_name.lower(), _mid.replace("_", " ")]):
        _ALIAS_INDEX.append((re.compile(rf"(?<![a-z0-9]){re.escape(normalize(_a))}(?![a-z0-9])"), _mid, len(_a)))
_ALIAS_INDEX.sort(key=lambda t: -t[2])


def resolve_merchant(text: str) -> str | None:
    t = normalize(text)
    if not t:
        return None
    for pat, mid, _ in _ALIAS_INDEX:
        if pat.search(t):
            return mid
    return None


# ------------------------------------------------------------ synthetic corpus

CITIES = ["bangalore", "blr", "mumbai", "mum", "delhi", "new delhi", "gurgaon", "pune", "hyderabad", "chennai", "kolkata", "noida", "in", "ind"]
TEMPLATES = [
    "{a}", "{A}", "POS {n} {A} {c}", "{A}*{c}", "UPI/{a}/{n}", "UPI-{A}-{n}@ybl", "ECOM {a}.com", "{a} india pvt ltd",
    "{A} {c} IN", "PAYU*{A}", "RAZ*{a}", "BILLDESK {A}", "{a} online payment", "www.{a}.in", "{A} PVT LTD {c}",
]

# generic phrases for merchants we don't know by name
GENERIC = {
    "dining": ["biryani house", "the brew pub", "chai point", "punjabi dhaba", "udupi hotel", "pizza corner", "barbeque nation", "kitchen and bar", "sweets and snacks", "food court", "coffee roasters", "haldirams"],
    "food_delivery": ["food delivery order", "eatsure", "box8 order", "faasos online"],
    "grocery": ["fresh mart", "kirana store", "supermarket", "more retail", "nature's basket", "spencer's retail", "vegetables and fruits", "star bazaar", "jiomart"],
    "online_shopping": ["online marketplace", "snapdeal", "tata cliq", "shopsy", "ecom order"],
    "fashion": ["lifestyle stores", "westside", "zara", "h&m", "pantaloons", "max fashion", "shoppers stop", "lenskart", "bata shoes", "mamaearth"],
    "electronics": ["vijay sales", "samsung store", "oneplus store", "mi store", "electronics mall", "sangeetha mobiles", "poorvika"],
    "travel_flights": ["akasa air", "spicejet", "vistara", "emirates airline", "goibibo flights", "ixigo flights", "yatra flights", "air ticket"],
    "travel_hotels": ["hyatt regency", "itc hotels", "the oberoi", "lemon tree hotels", "treebo", "fabhotels", "airbnb", "booking.com", "radisson"],
    "cabs": ["rapido", "blusmart", "namma yatri", "meru cabs", "fastag recharge", "toll plaza", "redbus"],
    "fuel": ["petrol pump", "filling station", "fuel station", "service station", "nayara energy", "jio-bp", "fuels and lubes"],
    "utilities": ["water bill", "electricity board", "bbmp", "municipal corporation", "power distribution", "tneb", "torrent power", "bses"],
    "telecom": ["act fibernet", "hathway broadband", "bsnl", "tata play", "dth recharge", "broadband bill", "prepaid recharge"],
    "entertainment": ["amazon prime video", "sonyliv", "zee5", "youtube premium", "steam games", "playstation store", "cinepolis", "concert tickets", "district by zomato"],
    "health": ["medplus", "wellness forever", "netmeds", "practo", "dental clinic", "diagnostic centre", "lal pathlabs", "hospital", "gym membership"],
    "education": ["tuition fees", "exam fee", "upgrad", "simplilearn", "physics wallah", "vedantu", "great learning"],
    "insurance": ["insurance premium", "max life", "tata aia", "bajaj allianz", "acko", "digit insurance", "sbi life"],
    "rent": ["house rent", "rentomojo", "paytm rent", "magicbricks rent", "rent for flat", "pg accommodation"],
    "government": ["passport seva", "traffic challan", "property tax", "tax payment", "rto fees", "e-challan"],
    "wallet_load": ["mobikwik wallet", "wallet topup", "freecharge wallet", "add money wallet", "gift card load"],
    "jewellery": ["joyalukkas", "senco gold", "caratlane", "pc jeweller", "bluestone", "gold and diamonds"],
    "others": ["hardware store", "stationery mart", "laundry service", "salon and spa", "pet store", "home centre", "urban company", "courier charges"],
}


# Category cue words: real merchant names are often "<proper noun> <cue>".
# Composing random prefixes with cues teaches the model the cues themselves.
PREFIXES = ["sri krishna", "new", "royal", "shree ganesh", "city", "green", "urban", "golden", "anand", "sai",
            "metro", "lakshmi", "star", "classic", "om sai", "balaji", "pioneer", "sunrise", "national", "modern",
            "mahalaxmi", "global", "prime", "sagar", "shiva", "jai hind", "orchid", "blue", "grand", "vasudev"]
CUES = {
    "dining": ["restaurant", "cafe", "bhavan", "sweets", "bakery", "dhaba", "pizzeria", "biryani", "kitchen", "eatery", "bar", "brewery", "tiffins", "canteen", "grill"],
    "food_delivery": ["food delivery", "cloud kitchen online", "meal delivery"],
    "grocery": ["supermarket", "provision store", "kirana", "general stores", "fresh", "dairy", "mart", "vegetables", "hypermarket"],
    "online_shopping": ["online store", "ecommerce", "marketplace", "internet pvt ltd"],
    "fashion": ["fashions", "boutique", "garments", "textiles", "footwear", "saree centre", "collections", "salon cosmetics", "optics"],
    "electronics": ["electronics", "mobiles", "digital world", "computers", "appliances", "gadgets"],
    "travel_flights": ["airlines", "aviation", "airways", "air ticketing", "flights"],
    "travel_hotels": ["hotel", "resort", "residency", "inn", "suites", "homestay", "palace hotel", "lodge"],
    "cabs": ["travels", "cabs", "taxi", "tours and travels", "auto", "bus service", "parking"],
    "fuel": ["petroleum", "fuel station", "filling station", "petrol pump", "service station", "fuels", "auto fuels"],
    "utilities": ["electricity", "water supply", "power corporation", "gas agency", "energy bill", "municipal"],
    "telecom": ["broadband", "fibernet", "telecom", "cable network", "recharge", "internet services"],
    "entertainment": ["cinemas", "multiplex", "gaming", "theatre", "entertainment", "amusement park", "streaming"],
    "health": ["pharmacy", "medicals", "chemist", "hospital", "clinic", "diagnostics", "healthcare", "dental", "fitness"],
    "education": ["school", "academy", "college", "institute", "tuitions", "classes", "university", "coaching"],
    "insurance": ["insurance", "life insurance", "general insurance", "assurance"],
    "rent": ["rent", "house rent", "rental", "pg rent", "flat rent"],
    "government": ["tax", "govt", "municipal tax", "challan", "treasury"],
    "wallet_load": ["wallet", "wallet topup", "prepaid wallet"],
    "jewellery": ["jewellers", "gold", "diamonds", "jewels", "ornaments"],
    "others": ["hardware", "stationers", "laundry", "furnishings", "services", "enterprises", "traders", "pet shop"],
}


def _render(alias: str, rng: random.Random) -> str:
    tpl = rng.choice(TEMPLATES)
    return tpl.format(a=alias, A=alias.upper(), c=rng.choice(CITIES).upper(), n=rng.randint(1000, 999999))


def synthetic_corpus(seed: int = 7, per_alias: int = 5) -> tuple[list[str], list[str], list[str]]:
    """Returns (texts, labels, groups). `groups` is the underlying phrase so the
    evaluation can hold out *whole merchants* rather than leaking them."""
    rng = random.Random(seed)
    X, y, g = [], [], []
    for _mid, (name, cat, aliases) in MERCHANTS.items():
        for a in sorted(set(aliases + [name.lower()])):
            for _ in range(per_alias):
                X.append(_render(a, rng)); y.append(cat); g.append(a)
    for cat, phrases in GENERIC.items():
        for p in phrases:
            for _ in range(per_alias + 2):
                X.append(_render(p, rng)); y.append(cat); g.append(p)
    for cat, cues in CUES.items():
        for cue in cues:
            for pre in rng.sample(PREFIXES, 8):
                name = f"{pre} {cue}"
                X.append(_render(name, rng)); y.append(cat); g.append(name)
    return X, y, g


# ------------------------------------------------------------ model

@dataclass
class Prediction:
    category: str
    confidence: float
    merchant: str | None
    method: str  # "merchant" | "model"
    alternatives: list[tuple[str, float]]


def _pipeline() -> Pipeline:
    feats = FeatureUnion([
        ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), sublinear_tf=True, min_df=1)),
        ("word", TfidfVectorizer(analyzer="word", ngram_range=(1, 2), sublinear_tf=True, token_pattern=r"[a-z0-9&']+")),
    ])
    return Pipeline([("feats", feats), ("clf", LogisticRegression(C=8.0, max_iter=2000))])


class Categorizer:
    def __init__(self):
        self._lock = threading.Lock()
        self.model: Pipeline | None = None
        self.metrics: dict = {}

    def train(self, feedback: list[dict] | None = None, evaluate: bool = True) -> dict:
        X, y, groups = synthetic_corpus()
        X = [normalize(x) for x in X]
        fb = feedback or []
        # user corrections are weighted by repetition: they reflect the truth for *this* user
        for f in fb:
            for _ in range(5):
                X.append(normalize(f["text"])); y.append(f["category"]); groups.append("fb:" + f["text"])
        metrics = {"train_size": len(X), "feedback_examples": len(fb), "classes": len(set(y))}
        if evaluate:
            # Hold out entire merchants/phrases (GroupShuffleSplit) so the score
            # measures generalisation to merchants the model has never seen.
            Xa, ya = np.array(X, dtype=object), np.array(y)
            split = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=0)
            tr, te = next(split.split(Xa, ya, groups))
            m = _pipeline().fit(Xa[tr].tolist(), ya[tr])
            pred = m.predict(Xa[te].tolist())
            metrics["unseen_merchant_accuracy"] = round(float(np.mean(pred == ya[te])), 4)
            metrics["unseen_merchant_macro_f1"] = round(float(f1_score(ya[te], pred, average="macro")), 4)
        model = _pipeline().fit(X, y)
        with self._lock:
            self.model, self.metrics = model, metrics
        return metrics

    def predict(self, text: str) -> Prediction:
        mid = resolve_merchant(text)
        if mid:
            return Prediction(MERCHANTS[mid][1], 0.99, mid, "merchant", [])
        if self.model is None:
            self.train(evaluate=False)
        t = normalize(text)
        if not t:
            return Prediction("others", 0.0, None, "model", [])
        proba = self.model.predict_proba([t])[0]
        classes = self.model.classes_
        order = np.argsort(-proba)
        alts = [(str(classes[i]), round(float(proba[i]), 3)) for i in order[:3]]
        cat, conf = alts[0]
        if conf < 0.35:
            cat = "others"
        return Prediction(cat, conf, None, "model", alts)


CATEGORY_KEYS = list(CATEGORIES)
