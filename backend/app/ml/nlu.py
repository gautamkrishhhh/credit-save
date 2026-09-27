"""Natural-language understanding for the Sage assistant.

* Intent classifier: TF-IDF (word 1-2 grams + char 2-4 grams) -> logistic
  regression, trained on a templated utterance corpus (slot-filled with real
  merchants/cards/amounts so it learns structure, not specific names).
* Entity extraction: amounts (Rs., 5k, 1.2 lakh), cards (catalogue aliases +
  wallet nicknames), merchants (alias match + fuzzy typo matching),
  categories (keyword lexicon), loyalty partners.
"""
from __future__ import annotations

import difflib
import random
import re
from dataclasses import dataclass, field

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import cross_val_score
from sklearn.pipeline import FeatureUnion, Pipeline

from ..data.cards import CARDS
from ..data.taxonomy import MERCHANTS
from .categorizer import resolve_merchant

# ----------------------------------------------------------------- lexicons

CARD_ALIASES: dict[str, list[str]] = {
    "hdfc_infinia": ["infinia", "hdfc infinia"],
    "hdfc_dcb": ["diners black", "dcb", "diners club black", "hdfc diners"],
    "hdfc_regalia_gold": ["regalia gold", "regalia"],
    "hdfc_millennia": ["millennia", "millenia"],
    "hdfc_swiggy": ["swiggy hdfc", "swiggy card", "swiggy credit card"],
    "tata_neu_infinity": ["tata neu", "neu infinity", "tata neu infinity"],
    "axis_atlas": ["atlas", "axis atlas"],
    "axis_magnus": ["magnus", "axis magnus"],
    "axis_ace": ["axis ace", "ace card", "ace"],
    "axis_flipkart": ["flipkart axis", "flipkart card", "flipkart credit card"],
    "airtel_axis": ["airtel axis", "airtel card", "airtel credit card"],
    "sbi_cashback": ["sbi cashback", "cashback sbi", "sbi cashback card"],
    "sbi_simplyclick": ["simplyclick", "simply click", "sbi simplyclick"],
    "icici_amazon_pay": ["amazon pay icici", "amazon icici", "amazon card", "amazon pay card", "apay"],
    "icici_emeralde": ["emeralde", "emerald private", "icici emeralde"],
    "amex_plat_travel": ["platinum travel", "amex plat travel", "amex platinum travel", "amex travel"],
    "amex_mrcc": ["mrcc", "membership rewards card", "amex mrcc"],
    "idfc_wealth": ["idfc wealth", "idfc first wealth", "first wealth"],
    "hsbc_live_plus": ["live+", "live plus", "hsbc live"],
    "scapia_federal": ["scapia"],
}

PARTNER_ALIASES = {
    "krisflyer": ["krisflyer", "kris flyer", "singapore airlines", "sq miles"],
    "air_india": ["maharaja club", "air india miles", "flying returns"],
    "qatar_avios": ["qatar", "privilege club", "qatar avios"],
    "ba_avios": ["british airways", "ba avios", "avios"],
    "turkish": ["turkish", "miles&smiles", "miles and smiles"],
    "etihad": ["etihad"],
    "emirates": ["emirates", "skywards"],
    "flying_blue": ["flying blue", "air france", "klm"],
    "marriott": ["marriott", "bonvoy"],
    "accor": ["accor", "all accor"],
    "itc": ["club itc", "itc hotels", "itc"],
    "ihg": ["ihg"],
}

CATEGORY_WORDS = {
    "food_delivery": ["food delivery", "food order", "ordering food", "order food"],
    "dining": ["dining", "restaurant", "restaurants", "eating out", "dinner", "lunch", "cafe", "bar", "pub"],
    "grocery": ["grocery", "groceries", "vegetables", "supermarket", "kirana", "instamart"],
    "online_shopping": ["online shopping", "shopping", "online", "ecommerce", "e-commerce"],
    "fashion": ["clothes", "clothing", "fashion", "shoes", "apparel", "beauty", "makeup"],
    "electronics": ["electronics", "laptop", "phone purchase", "iphone", "tv", "gadget", "gadgets"],
    "travel_flights": ["flight", "flights", "airfare", "air ticket", "air tickets", "airline"],
    "travel_hotels": ["hotel", "hotels", "stay", "resort", "accommodation"],
    "cabs": ["cab", "cabs", "taxi", "auto", "commute", "train", "metro", "bus"],
    "fuel": ["fuel", "petrol", "diesel", "gas station", "cng"],
    "utilities": ["electricity", "utility", "utilities", "water bill", "gas bill", "bills", "bill payment", "bill"],
    "telecom": ["mobile recharge", "recharge", "broadband", "postpaid", "wifi", "dth"],
    "entertainment": ["movie", "movies", "ott", "subscription", "streaming", "concert", "gaming"],
    "health": ["medicine", "medicines", "pharmacy", "doctor", "hospital", "gym", "health"],
    "education": ["education", "school fee", "school fees", "tuition", "college fees", "course"],
    "insurance": ["insurance", "premium"],
    "rent": ["rent", "house rent"],
    "government": ["tax", "taxes", "income tax", "challan", "government"],
    "wallet_load": ["wallet load", "wallet", "paytm wallet"],
    "jewellery": ["gold", "jewellery", "jewelry"],
}

_AMOUNT_RE = re.compile(
    r"(?:(?:rs\.?|inr|₹)\s*)?(\d+(?:,\d+)*(?:\.\d+)?)\s*(k|thousand|lakhs?|lacs?|l|cr|crores?)?\b", re.I)
_MULT = {"k": 1e3, "thousand": 1e3, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5, "l": 1e5,
         "cr": 1e7, "crore": 1e7, "crores": 1e7}


@dataclass
class Entities:
    amount: float | None = None
    numbers: list[float] = field(default_factory=list)
    cards: list[str] = field(default_factory=list)
    user_cards: list[int] = field(default_factory=list)
    merchant: str | None = None
    category: str | None = None
    partner: str | None = None


def _find_phrases(text: str, table: dict[str, list[str]]) -> list[tuple[int, str, str]]:
    hits = []
    for key, phrases in table.items():
        for p in sorted(phrases, key=len, reverse=True):
            for m in re.finditer(rf"(?<![a-z0-9]){re.escape(p)}(?![a-z0-9])", text):
                hits.append((m.start(), key, p))
    # keep longest non-overlapping
    hits.sort(key=lambda h: (h[0], -len(h[2])))
    out, end = [], -1
    for h in hits:
        if h[0] >= end:
            out.append(h)
            end = h[0] + len(h[2])
    return out


def extract(text: str, wallet: list[dict] | None = None) -> Entities:
    t = text.lower()
    e = Entities()

    # cards first -- then blank them out so "flipkart axis" isn't read as merchant Flipkart
    masked = t
    for uc in wallet or []:
        nick = (uc.get("nickname") or "").lower()
        if nick and len(nick) > 2 and re.search(rf"(?<![a-z0-9]){re.escape(nick)}(?![a-z0-9])", masked):
            e.user_cards.append(uc["id"])
            if uc["card_id"] not in e.cards:
                e.cards.append(uc["card_id"])
            masked = masked.replace(nick, " " * len(nick))
    for _, cid, phrase in _find_phrases(masked, CARD_ALIASES):
        if cid not in e.cards:
            e.cards.append(cid)
        masked = masked.replace(phrase, " " * len(phrase), 1)

    # partners (may also mask 'air india' miles phrases)
    ph = _find_phrases(masked, PARTNER_ALIASES)
    if ph:
        e.partner = ph[0][1]

    # amounts
    for m in _AMOUNT_RE.finditer(masked):
        raw = m.group(1).replace(",", "")
        try:
            v = float(raw)
        except ValueError:
            continue
        unit = (m.group(2) or "").lower()
        v *= _MULT.get(unit, 1)
        if 0 < v < 1e9:
            e.numbers.append(v)
    if e.numbers:
        e.amount = e.numbers[0]

    # merchant: exact alias, then fuzzy for typos ("swigy", "amazn")
    e.merchant = resolve_merchant(masked)
    if not e.merchant:
        tokens = re.findall(r"[a-z][a-z0-9]{3,}", masked)
        vocab = {}
        for mid, (name, _, aliases) in MERCHANTS.items():
            for a in aliases + [name.lower()]:
                if " " not in a and len(a) >= 4:
                    vocab[a] = mid
        stop = {"which", "card", "best", "should", "what", "about", "spend", "spending", "worth", "points", "much",
                "month", "this", "that", "with", "have", "using", "offers", "offer", "compare", "tell", "more",
                "order", "ordering", "online", "shopping", "bill", "bills", "flight", "hotel", "hotels", "flights"}
        for tok in tokens:
            if tok in stop:
                continue
            m = difflib.get_close_matches(tok, list(vocab), n=1, cutoff=0.84)
            if m:
                e.merchant = vocab[m[0]]
                break

    cats = _find_phrases(masked, CATEGORY_WORDS)
    if cats:
        e.category = cats[0][1]
    return e


# ----------------------------------------------------------------- intents

_M = ["swiggy", "zomato", "amazon", "flipkart", "myntra", "uber", "bigbasket", "makemytrip", "netflix", "croma", "blinkit", "starbucks", "taj", "airtel"]
_C = ["atlas", "infinia", "regalia", "millennia", "magnus", "sbi cashback", "amazon pay icici", "ace", "scapia", "platinum travel"]
_CAT = ["fuel", "groceries", "dining", "flights", "hotels", "electricity bill", "rent", "insurance", "shopping", "movies", "food delivery"]
_P = ["krisflyer", "marriott", "accor", "qatar", "air india miles", "turkish", "avios"]
_A = ["500", "2000", "rs 5000", "₹12,000", "5k", "1.5 lakh", "800", "25000", "10k"]

INTENT_TEMPLATES: dict[str, list[str]] = {
    "best_card": [
        "which card should i use for {m}", "best card for {m}", "what card for {cat}", "which card for {a} on {m}",
        "i am spending {a} at {m} which card", "{m} {a}", "best card to pay {a} for {cat}", "what should i swipe at {m}",
        "which credit card gives most rewards on {cat}", "card for {m} order", "i want to buy something on {m} for {a}",
        "maximum cashback on {m}", "which card gives best return for {cat}", "paying {a} for {cat} which card",
        "booking {cat} worth {a}", "which of my cards for {m}", "use which card at {m}", "{cat} payment of {a}",
    ],
    "points_value": [
        "how much are my points worth", "what is the value of my rewards", "total points value", "my reward points balance",
        "how many points do i have", "what's my {c} points worth", "value of my miles", "net worth of my rewards",
        "show my points", "how much reward balance", "points balance across cards", "how much is {c} balance worth",
    ],
    "redeem": [
        "how should i redeem my {c} points", "best way to use my points", "best redemption for {c}", "where to transfer my miles",
        "should i transfer points to {p}", "how to redeem reward points", "best use of my {c} miles", "redeem points",
        "what is the best redemption option", "transfer partners for {c}", "cash out my points", "maximize value of my points",
    ],
    "goal": [
        "i need {n} {p} miles", "how can i get {n} {p} points", "plan to reach {n} {p}", "i want {n} {p} miles for a flight",
        "can i transfer enough for {n} {p}", "goal {n} {p} points", "how to collect {n} miles in {p}", "{n} {p} miles needed",
    ],
    "discover": [
        "suggest a new credit card", "which credit card should i get", "recommend me a card", "best card for my spending",
        "what card should i apply for", "which new card will save me most", "is there a better card for me",
        "card recommendation", "which card to add to my wallet", "should i get {c}", "should i apply for {c}",
        "what is the best credit card in india for me", "find me a card", "upgrade my card",
    ],
    "compare": [
        "compare {c} and {c2}", "{c} vs {c2}", "{c} or {c2}", "difference between {c} and {c2}", "which is better {c} or {c2}",
        "compare {c} with {c2}", "{c} versus {c2} which one",
    ],
    "card_info": [
        "tell me about {c}", "what are the benefits of {c}", "annual fee of {c}", "{c} features", "{c} reward rate",
        "lounge access on {c}", "details of {c}", "what does {c} offer", "how good is {c}", "{c} review", "{c} forex markup",
    ],
    "spend_summary": [
        "how much did i spend this month", "my spending summary", "spend on {cat} this month", "where is my money going",
        "total spend", "monthly expenses", "show my expenses", "what did i spend on {m}", "breakdown of my spending",
        "how much have i spent", "top spending categories",
    ],
    "missed": [
        "how much did i lose by using wrong card", "missed savings", "am i using the right cards", "how much could i have saved",
        "reward efficiency", "did i use the best card", "money left on the table", "which transactions were not optimal",
        "how optimal is my card usage", "lost rewards",
    ],
    "milestones": [
        "fee waiver progress", "milestones", "how far from my milestone", "will my annual fee be waived", "milestone status for {c}",
        "how much more to spend for fee waiver", "track milestones", "am i on track for milestone benefits",
    ],
    "offers": [
        "any offers on {m}", "offers for my cards", "deals on {m}", "discounts available", "current card offers",
        "is there any discount on {m}", "bank offers", "coupons for {m}",
    ],
    "forecast": [
        "how much will i spend next month", "predict my spending", "forecast my expenses", "next month budget",
        "expected spend on {cat}", "spending prediction", "projected spend", "future expenses",
    ],
    "anomaly": [
        "any unusual transactions", "suspicious spends", "flag odd transactions", "any fraud on my card",
        "unusual activity", "strange charges", "outliers in my spending", "big unusual purchases",
    ],
    "greeting": ["hi", "hello", "hey", "good morning", "hey sage", "hello there", "yo", "namaste"],
    "help": ["what can you do", "help", "how does this work", "what can i ask", "commands", "features", "guide me"],
    "thanks": ["thanks", "thank you", "great thanks", "awesome", "cool thanks", "perfect", "ok thanks"],
}


def utterance_corpus(seed: int = 3, per_template: int = 4) -> tuple[list[str], list[str]]:
    rng = random.Random(seed)
    X, y = [], []
    for intent, tpls in INTENT_TEMPLATES.items():
        for tpl in tpls:
            n = per_template if "{" in tpl else 2
            for _ in range(n):
                c, c2 = rng.sample(_C, 2)
                s = tpl.format(m=rng.choice(_M), c=c, c2=c2, cat=rng.choice(_CAT), p=rng.choice(_P),
                               a=rng.choice(_A), n=rng.choice(["30000", "60k", "45,000", "1 lakh", "80000"]))
                X.append(s); y.append(intent)
    return X, y


class IntentClassifier:
    def __init__(self):
        self.model: Pipeline | None = None
        self.metrics: dict = {}

    def train(self) -> dict:
        X, y = utterance_corpus()
        pipe = Pipeline([
            ("feats", FeatureUnion([
                ("w", TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True)),
                ("c", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), sublinear_tf=True)),
            ])),
            ("clf", LogisticRegression(C=10, max_iter=3000)),
        ])
        scores = cross_val_score(pipe, X, y, cv=5)
        self.model = pipe.fit(X, y)
        self.metrics = {"examples": len(X), "intents": len(INTENT_TEMPLATES), "cv_accuracy": round(float(np.mean(scores)), 4)}
        return self.metrics

    def predict(self, text: str) -> tuple[str, float, list[tuple[str, float]]]:
        if self.model is None:
            self.train()
        p = self.model.predict_proba([text.lower()])[0]
        order = np.argsort(-p)
        cls = self.model.classes_
        top = [(str(cls[i]), round(float(p[i]), 3)) for i in order[:3]]
        return top[0][0], top[0][1], top
