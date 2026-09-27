"""HTTP API (FastAPI) + static SPA hosting. Thin layer: validation, wiring,
error mapping -- all logic lives in services/ and core/."""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .core.db import Database
from .core.rewards import VALUE_MODES
from .data.cards import CARDS, get_card
from .data.offers import OFFERS
from .data.partners import PARTNERS
from .data.taxonomy import CATEGORIES, MERCHANTS, merchant_name
from .ml.categorizer import Categorizer
from .ml.nlu import IntentClassifier
from .services import demo, insights as insights_svc, recommend, redeem
from .services.assistant import Sage
from .services.ingest import Ingestor
from .services.wallet import card_summary, value_mode, wallet

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"


# ---------------------------------------------------------------- request models
class CardIn(BaseModel):
    card_id: str
    nickname: Optional[str] = None
    last4: Optional[str] = Field(None, pattern=r"^\d{4}$")
    points_balance: float = Field(0, ge=0)
    points_expiry: Optional[str] = None
    credit_limit: Optional[float] = None
    statement_day: Optional[int] = Field(None, ge=1, le=31)

class CardPatch(BaseModel):
    nickname: Optional[str] = None
    last4: Optional[str] = Field(None, pattern=r"^\d{4}$")
    points_balance: Optional[float] = Field(None, ge=0)
    points_expiry: Optional[str] = None
    credit_limit: Optional[float] = None
    statement_day: Optional[int] = Field(None, ge=1, le=31)

class TxnIn(BaseModel):
    amount: float = Field(..., gt=0)
    description: Optional[str] = None
    merchant: Optional[str] = None
    category: Optional[str] = None
    user_card_id: Optional[int] = None
    txn_date: Optional[str] = None
    is_refund: bool = False

class TxnPatch(BaseModel):
    category: Optional[str] = None
    user_card_id: Optional[int] = None

class SmsIn(BaseModel):
    text: str

class BestCardIn(BaseModel):
    amount: float = Field(..., gt=0)
    merchant: Optional[str] = None
    category: Optional[str] = None
    query: Optional[str] = None  # free text, e.g. "swiggy" or "HP petrol pump"

class DiscoverIn(BaseModel):
    profile: Optional[dict[str, float]] = None  # {category: monthly amount}
    income_lpa: Optional[float] = None

class GoalIn(BaseModel):
    partner: str
    target_points: float = Field(..., gt=0)
    name: Optional[str] = None
    save: bool = False

class ChatIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=500)

class ClassifyIn(BaseModel):
    text: str

class SettingsIn(BaseModel):
    value_mode: Optional[str] = None
    income_lpa: Optional[float] = None


class State:
    def __init__(self, db_path: str | None = None):
        self.db = Database(db_path)
        self.categorizer = Categorizer()
        self.intents = IntentClassifier()
        self.ingestor = Ingestor(self.db, self.categorizer)
        self.sage = Sage(self.db, self.intents)
        self.ml_ready = threading.Event()
        self.train_seconds: float | None = None

    def train_models(self) -> dict:
        t0 = time.time()
        cm = self.categorizer.train(self.db.list_feedback(), evaluate=True)
        im = self.intents.train()
        self.train_seconds = round(time.time() - t0, 2)
        self.ml_ready.set()
        return {"categorizer": cm, "intent_classifier": im, "seconds": self.train_seconds}


def create_app(db_path: str | None = None, train_in_background: bool = True) -> FastAPI:
    st = State(db_path)
    app = FastAPI(title="CreditSage API", version="1.0.0")
    app.state.s = st
    if train_in_background:
        threading.Thread(target=st.train_models, daemon=True).start()
    else:
        st.train_models()

    # ------------------------------------------------------------ meta
    @app.get("/api/health")
    def health():
        return {"status": "ok", "ml_ready": st.ml_ready.is_set(), "cards": len(st.db.list_user_cards()),
                "transactions": len(st.db.list_transactions())}

    @app.get("/api/catalog/cards")
    def catalog_cards():
        mode = value_mode(st.db)
        return [card_summary(c, mode) for c in CARDS]

    @app.get("/api/catalog/cards/{card_id}")
    def catalog_card(card_id: str):
        c = get_card(card_id)
        if not c:
            raise HTTPException(404, "card not found")
        return card_summary(c, value_mode(st.db))

    @app.get("/api/catalog/meta")
    def catalog_meta():
        return {"categories": CATEGORIES,
                "merchants": {k: {"name": v[0], "category": v[1]} for k, v in MERCHANTS.items()},
                "partners": PARTNERS, "value_modes": VALUE_MODES}

    @app.get("/api/settings")
    def get_settings():
        inc = st.db.get_setting("income_lpa")
        return {"value_mode": value_mode(st.db), "income_lpa": float(inc) if inc else None}

    @app.put("/api/settings")
    def put_settings(body: SettingsIn):
        if body.value_mode is not None:
            if body.value_mode not in VALUE_MODES:
                raise HTTPException(422, f"value_mode must be one of {VALUE_MODES}")
            st.db.set_setting("value_mode", body.value_mode)
        if body.income_lpa is not None:
            st.db.set_setting("income_lpa", str(body.income_lpa))
        return get_settings()

    # ------------------------------------------------------------ wallet
    @app.get("/api/wallet")
    def get_wallet():
        return wallet(st.db)

    @app.post("/api/wallet", status_code=201)
    def add_card(body: CardIn):
        if not get_card(body.card_id):
            raise HTTPException(422, "unknown card_id")
        uid = st.db.add_user_card(**body.model_dump())
        return next(c for c in wallet(st.db) if c["id"] == uid)

    @app.patch("/api/wallet/{uc_id}")
    def patch_card(uc_id: int, body: CardPatch):
        if not st.db.get_user_card(uc_id):
            raise HTTPException(404, "card not in wallet")
        st.db.update_user_card(uc_id, **body.model_dump(exclude_unset=True))
        return next(c for c in wallet(st.db) if c["id"] == uc_id)

    @app.delete("/api/wallet/{uc_id}", status_code=204)
    def delete_card(uc_id: int):
        st.db.delete_user_card(uc_id)

    # ------------------------------------------------------------ transactions
    def _decorate(t: dict) -> dict:
        uc = st.db.get_user_card(t["user_card_id"]) if t["user_card_id"] else None
        card = get_card(uc["card_id"]) if uc else None
        return {**t, "merchant_name": merchant_name(t["merchant"]), "category_name": CATEGORIES.get(t["category"]),
                "card_name": (uc["nickname"] or card["name"]) if uc and card else None}

    @app.get("/api/transactions")
    def list_txns(start: Optional[str] = None, end: Optional[str] = None, user_card_id: Optional[int] = None,
                  limit: int = Query(500, le=5000)):
        return [_decorate(t) for t in st.db.list_transactions(start, end, user_card_id, limit)]

    @app.post("/api/transactions", status_code=201)
    def add_txn(body: TxnIn):
        if body.category and body.category not in CATEGORIES:
            raise HTTPException(422, "unknown category")
        if body.merchant and body.merchant not in MERCHANTS:
            raise HTTPException(422, "unknown merchant id")
        if not (body.description or body.merchant):
            raise HTTPException(422, "description or merchant required")
        t = st.ingestor.add(**body.model_dump())
        return {**_decorate(t), "classification": t["classification"]}

    @app.patch("/api/transactions/{tid}")
    def patch_txn(tid: int, body: TxnPatch):
        if not st.db.get_transaction(tid):
            raise HTTPException(404, "transaction not found")
        if body.category:
            if body.category not in CATEGORIES:
                raise HTTPException(422, "unknown category")
            st.ingestor.recategorize(tid, body.category)
        if body.user_card_id is not None:
            st.db.update_transaction(tid, user_card_id=body.user_card_id)
        return _decorate(st.db.get_transaction(tid))

    @app.delete("/api/transactions/{tid}", status_code=204)
    def delete_txn(tid: int):
        st.db.delete_transaction(tid)

    @app.post("/api/transactions/sms/preview")
    def sms_preview(body: SmsIn):
        return st.ingestor.preview_sms(body.text)

    @app.post("/api/transactions/sms/import")
    def sms_import(body: SmsIn):
        r = st.ingestor.import_sms(body.text)
        return {"imported": [_decorate(t) for t in r["imported"]], "skipped": r["skipped"]}

    # ------------------------------------------------------------ recommendations
    @app.post("/api/recommend/best-card")
    def rec_best(body: BestCardIn):
        merchant, category = body.merchant, body.category
        classification = None
        if body.query and not (merchant or category):
            classification = st.ingestor.classify(body.query)
            merchant, category = classification["merchant"], classification["category"]
        r = recommend.best_card(st.db, body.amount, merchant, category)
        r["classification"] = classification
        return r

    @app.post("/api/recommend/discover")
    def rec_discover(body: DiscoverIn):
        buckets = {(c, None): v for c, v in body.profile.items() if v > 0 and c in CATEGORIES} if body.profile else None
        inc = body.income_lpa if body.income_lpa is not None else (float(st.db.get_setting("income_lpa")) if st.db.get_setting("income_lpa") else None)
        r = recommend.discover(st.db, buckets, inc)
        r["current_per_card"] = list(r["current_per_card"].values())
        return r

    @app.get("/api/recommend/compare")
    def rec_compare(ids: str):
        card_ids = [i for i in ids.split(",") if get_card(i)]
        if not 2 <= len(card_ids) <= 4:
            raise HTTPException(422, "pass 2-4 valid card ids")
        return recommend.compare(st.db, card_ids)

    @app.get("/api/missed-savings")
    def missed(start: str, end: str):
        return recommend.missed_savings(st.db, start, end)

    # ------------------------------------------------------------ rewards
    @app.get("/api/redeem")
    def redeem_opts():
        return redeem.redemption_options(st.db)

    @app.post("/api/redeem/goal")
    def redeem_goal(body: GoalIn):
        try:
            plan = redeem.goal_plan(st.db, body.partner, body.target_points)
        except ValueError as e:
            raise HTTPException(422, str(e))
        if body.save:
            st.db.add_goal(body.name or f"{body.target_points:,.0f} {PARTNERS[body.partner]['name']}", body.partner, body.target_points)
        return plan

    @app.get("/api/goals")
    def goals():
        out = []
        for g in st.db.list_goals():
            out.append({**g, "plan": redeem.goal_plan(st.db, g["partner"], g["target_points"])})
        return out

    @app.delete("/api/goals/{gid}", status_code=204)
    def del_goal(gid: int):
        st.db.delete_goal(gid)

    @app.get("/api/milestones")
    def get_milestones():
        return redeem.milestones(st.db)

    @app.get("/api/offers")
    def offers(wallet_only: bool = False):
        ucs = st.db.list_user_cards()
        out = []
        for o in OFFERS:
            eligible = []
            for uc in ucs:
                c = get_card(uc["card_id"])
                if ("cards" in o and c["id"] in o["cards"]) or ("issuers" in o and c["issuer"] in o["issuers"]):
                    eligible.append(uc["nickname"] or c["name"])
            if wallet_only and not eligible:
                continue
            out.append({**o, "merchant_name": merchant_name(o.get("merchant")) or CATEGORIES.get(o.get("category") or "", ""),
                        "eligible_cards": eligible})
        return out

    # ------------------------------------------------------------ insights
    @app.get("/api/dashboard")
    def dashboard():
        return insights_svc.dashboard(st.db)

    @app.get("/api/insights")
    def get_insights():
        return insights_svc.insights(st.db)

    # ------------------------------------------------------------ assistant
    @app.post("/api/assistant/chat")
    def chat(body: ChatIn):
        return st.sage.respond(body.message)

    @app.get("/api/assistant/history")
    def chat_history():
        return st.db.list_chat()

    @app.delete("/api/assistant/history", status_code=204)
    def chat_clear():
        st.db.clear_chat()

    # ------------------------------------------------------------ ML ops
    @app.post("/api/ml/classify")
    def ml_classify(body: ClassifyIn):
        return st.ingestor.classify(body.text)

    @app.get("/api/ml/status")
    def ml_status():
        return {"ready": st.ml_ready.is_set(), "train_seconds": st.train_seconds,
                "categorizer": st.categorizer.metrics, "intent_classifier": st.intents.metrics,
                "feedback_examples": len(st.db.list_feedback())}

    @app.post("/api/ml/retrain")
    def ml_retrain():
        r = st.train_models()
        st.ingestor.rescore_anomalies()
        return r

    # ------------------------------------------------------------ demo
    @app.post("/api/demo/seed")
    def demo_seed():
        return demo.seed_demo(st.db, st.ingestor)

    @app.post("/api/demo/reset")
    def demo_reset():
        st.db.reset()
        return {"ok": True}

    # ------------------------------------------------------------ SPA
    if FRONTEND.exists():
        app.mount("/static", StaticFiles(directory=FRONTEND), name="static")

        @app.get("/")
        def index():
            return FileResponse(FRONTEND / "index.html")

    return app

