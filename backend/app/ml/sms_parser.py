"""Bank SMS / email alert parser.

Extracts amount, card last-4, merchant text, date, bank and direction from
the common Indian credit-card alert formats, e.g.

  "Rs.1,250.00 spent on HDFC Bank Card x1234 at SWIGGY on 2026-09-12:20:11:05"
  "INR 2,499.00 spent using Axis Bank Card XX5678 on 12-09-26 at AMAZON. Avl Limit: INR 1,20,000"
  "Your ICICI Bank Credit Card XX9012 has been used for a transaction of INR 499.00 on Sep 12, 2026 at NETFLIX."
  "Thank you for using SBI Card ending 3456 for Rs 890 at ZOMATO on 12/09/2026."
  "Refund of Rs 499 credited to your card ending 1234 from MYNTRA"

Rule-based (regex) on purpose: bank templates are rigid, and precision
matters more than recall -- anything unparsed is surfaced to the user.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date, datetime

AMOUNT = r"(?:rs\.?|inr|₹)\s*([0-9][0-9,]*(?:\.\d{1,2})?)"
_AMOUNT_RE = re.compile(AMOUNT, re.I)
_LAST4_RE = re.compile(r"(?:card|a/c|ac)\s*(?:no\.?\s*)?(?:ending(?: with)?|ending in|x+|\*+|xx+|no\.?)?\s*[x*]*\s*(\d{4})\b", re.I)
_MERCHANT_RES = [
    re.compile(r"\bat\s+(.+?)(?=\s+on\s+\d|\s+on\s+[a-z]{3}\b|\.\s|\.$|\s+avl|\s+avbl|\s+ref|\s+txn|\s+if not|$)", re.I),
    *[re.compile(rf"\b{kw}\s+(.+?)(?=\s+on\s+\d|\.\s|\.$|\s+avl|\s+ref|$)", re.I) for kw in ("from", "towards", "info:?", "to")],
]
_BANKS = ["HDFC", "ICICI", "Axis", "SBI", "Kotak", "American Express", "Amex", "IDFC", "HSBC", "Federal", "Yes Bank", "IndusInd", "AU", "RBL", "Standard Chartered"]
_REFUND_RE = re.compile(r"\b(refund|reversal|reversed|credited|cashback of)\b", re.I)
_DEBIT_RE = re.compile(r"\b(spent|used|debited|purchase|transaction of|txn of|paid|using|charged)\b", re.I)

_DATE_FORMATS = ["%Y-%m-%d", "%d-%m-%Y", "%d-%m-%y", "%d/%m/%Y", "%d/%m/%y", "%d-%b-%Y", "%d-%b-%y", "%d %b %Y",
                 "%b %d, %Y", "%b %d %Y", "%d%b%y", "%d %b %y"]
_DATE_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\d{1,2}[- ]?[A-Za-z]{3}[- ]?\d{2,4}|[A-Za-z]{3} \d{1,2},? \d{4})")


@dataclass
class ParsedSMS:
    ok: bool
    amount: float | None = None
    last4: str | None = None
    merchant_text: str | None = None
    txn_date: str | None = None
    bank: str | None = None
    is_refund: bool = False
    raw: str = ""
    error: str | None = None

    def dict(self) -> dict:
        return asdict(self)


def _parse_date(s: str) -> str | None:
    s = s.strip().rstrip(",")
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _clean_merchant(m: str) -> str:
    m = re.sub(r"\s+", " ", m).strip(" .,:-")
    m = re.sub(r"\s+on\s*$", "", m, flags=re.I)
    return m[:80]


def parse_sms(text: str, today: date | None = None) -> ParsedSMS:
    raw = text.strip()
    if not raw:
        return ParsedSMS(False, raw=raw, error="empty message")
    amt = _AMOUNT_RE.search(raw)
    if not amt:
        return ParsedSMS(False, raw=raw, error="no amount found")
    amount = float(amt.group(1).replace(",", ""))
    if amount <= 0:
        return ParsedSMS(False, raw=raw, error="non-positive amount")

    is_refund = bool(_REFUND_RE.search(raw)) and not re.search(r"\bspent\b", raw, re.I)
    if not is_refund and not _DEBIT_RE.search(raw):
        return ParsedSMS(False, raw=raw, amount=amount, error="not a card transaction alert")

    last4 = None
    if m := _LAST4_RE.search(raw):
        last4 = m.group(1)

    merchant = None
    for rx in _MERCHANT_RES:
        for m in rx.finditer(raw):
            cand = _clean_merchant(m.group(1))
            # skip matches that are just the amount/card phrase
            if cand and not _AMOUNT_RE.match(cand) and not re.match(r"(your )?(\w+ )?(bank )?(credit )?(card|a/c)", cand, re.I):
                merchant = cand
                break
        if merchant:
            break

    txn_date = None
    for m in _DATE_RE.finditer(raw):
        if d := _parse_date(m.group(1)):
            txn_date = d
            break
    txn_date = txn_date or (today or date.today()).isoformat()

    bank = next((b for b in _BANKS if re.search(rf"\b{re.escape(b)}\b", raw, re.I)), None)
    if bank == "Amex":
        bank = "American Express"
    return ParsedSMS(True, amount, last4, merchant, txn_date, bank, is_refund, raw)


def split_messages(blob: str) -> list[str]:
    """A pasted dump may hold many SMS: split on blank lines, else on lines."""
    parts = [p.strip() for p in re.split(r"\n\s*\n", blob) if p.strip()]
    if len(parts) == 1:
        lines = [l.strip() for l in blob.splitlines() if l.strip()]
        if len(lines) > 1 and all(_AMOUNT_RE.search(l) for l in lines):
            return lines
    return parts
