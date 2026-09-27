"""Transaction ingestion pipeline:
raw input (manual form / bank SMS) -> merchant resolution -> ML category ->
card matching by last-4 -> persistence -> anomaly re-scoring."""
from __future__ import annotations

from datetime import date

from ..core.db import Database
from ..data.cards import get_card
from ..data.taxonomy import CATEGORIES, merchant_category
from ..ml.anomaly import score_transactions
from ..ml.categorizer import Categorizer, resolve_merchant
from ..ml.sms_parser import parse_sms, split_messages


class Ingestor:
    def __init__(self, db: Database, categorizer: Categorizer):
        self.db, self.cat = db, categorizer

    def classify(self, text: str, merchant: str | None = None, category: str | None = None) -> dict:
        merchant = merchant or resolve_merchant(text or "")
        if category and category in CATEGORIES:
            return {"merchant": merchant, "category": category, "confidence": 1.0, "method": "user"}
        if merchant and merchant_category(merchant):
            return {"merchant": merchant, "category": merchant_category(merchant), "confidence": 0.99, "method": "merchant"}
        p = self.cat.predict(text or "")
        return {"merchant": p.merchant, "category": p.category, "confidence": round(p.confidence, 3),
                "method": p.method, "alternatives": p.alternatives}

    def add(self, amount: float, description: str | None = None, merchant: str | None = None,
            category: str | None = None, user_card_id: int | None = None, txn_date: str | None = None,
            source: str = "manual", is_refund: bool = False, rescore: bool = True) -> dict:
        c = self.classify(description or merchant or "", merchant, category)
        tid = self.db.add_transaction(
            user_card_id=user_card_id, amount=float(amount), merchant=c["merchant"], description=description,
            category=c["category"], category_confidence=c["confidence"], txn_date=txn_date or date.today().isoformat(),
            source=source, is_refund=is_refund)
        if rescore:
            self.rescore_anomalies()
        return {**self.db.get_transaction(tid), "classification": c}

    def match_card(self, last4: str | None, bank: str | None) -> int | None:
        cards = self.db.list_user_cards()
        if last4:
            for uc in cards:
                if uc["last4"] == last4:
                    return uc["id"]
        if bank:
            by_bank = [uc for uc in cards if bank.lower() in (get_card(uc["card_id"]) or {}).get("issuer", "").lower()]
            if len(by_bank) == 1:
                return by_bank[0]["id"]
        return None

    def preview_sms(self, blob: str) -> list[dict]:
        out = []
        for msg in split_messages(blob):
            p = parse_sms(msg)
            row = p.dict()
            if p.ok:
                row["classification"] = self.classify(p.merchant_text or "")
                row["user_card_id"] = self.match_card(p.last4, p.bank)
            out.append(row)
        return out

    def import_sms(self, blob: str) -> dict:
        imported, skipped = [], []
        for row in self.preview_sms(blob):
            if not row["ok"]:
                skipped.append({"raw": row["raw"], "error": row["error"]})
                continue
            t = self.add(row["amount"], description=row["merchant_text"] or row["raw"][:60],
                         merchant=row["classification"]["merchant"], category=row["classification"]["category"],
                         user_card_id=row["user_card_id"], txn_date=row["txn_date"], source="sms",
                         is_refund=row["is_refund"], rescore=False)
            imported.append(t)
        if imported:
            self.rescore_anomalies()
        return {"imported": imported, "skipped": skipped}

    def recategorize(self, tid: int, category: str) -> dict:
        t = self.db.get_transaction(tid)
        if not t:
            raise KeyError(tid)
        self.db.update_transaction(tid, category=category, category_confidence=1.0)
        if t.get("description"):
            self.db.add_feedback(t["description"], category)
        return self.db.get_transaction(tid)

    def rescore_anomalies(self) -> int:
        txns = [t for t in self.db.list_transactions() if not t["is_refund"]]
        n = 0
        for s in score_transactions(txns):
            self.db.update_transaction(s["id"], anomaly_score=s["score"], is_anomaly=int(s["is_anomaly"]))
            n += s["is_anomaly"]
        return n
