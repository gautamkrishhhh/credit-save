"""Rewards engine -- the lowest-level domain layer.

Pure, deterministic functions (no I/O) that answer: "if I swipe card C for
transaction T, given everything already spent on C this month, how many
points do I earn and what are they worth?"

Handles the messy real-world rules:
  * merchant-specific > category-specific > spend-threshold > base rate
  * monthly point caps per rule, with overflow falling back to base (or not)
  * a capped base rate (e.g. 1% capped at 1,000/month)
  * month-to-date spend thresholds that switch rates mid-transaction
  * excluded categories (fuel, rent, wallet loads...)
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..data.partners import PARTNERS

VALUE_MODES = ("cash", "portal", "best")


@dataclass(frozen=True)
class Txn:
    amount: float
    category: str
    merchant: str | None = None


@dataclass
class MonthState:
    """Running per-card, per-calendar-month accumulator."""
    spend: float = 0.0
    points_by_rule: dict[str, float] = field(default_factory=dict)

    def copy(self) -> "MonthState":
        return MonthState(self.spend, dict(self.points_by_rule))


@dataclass
class Segment:
    rule_id: str
    label: str
    amount: float
    points: float


@dataclass
class Earn:
    card_id: str
    points: float
    value: float
    segments: list[Segment]
    excluded: bool = False
    capped: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def effective_rate(self) -> float:
        """Reward value as % of the amount spent."""
        spent = sum(s.amount for s in self.segments) or 0.0
        return 0.0 if spent <= 0 else 100.0 * self.value / spent

    @property
    def primary_rule(self) -> str:
        if not self.segments:
            return "excluded" if self.excluded else "none"
        return max(self.segments, key=lambda s: s.points).label


# ---------------------------------------------------------------- valuation

def best_transfer(card: dict) -> tuple[str | None, float]:
    """Best (partner_id, rupee value per card point) via transfer partners."""
    best_id, best_val = None, 0.0
    for pid, ratio in card.get("transfer", {}).items():
        v = ratio * PARTNERS[pid]["value_inr"]
        if v > best_val:
            best_id, best_val = pid, v
    return best_id, best_val


def point_value(card: dict, mode: str = "best") -> float:
    pv = card["point_value"]
    if mode == "cash":
        return pv["cash"] or pv["portal"] * 0.5  # coins with no cash-out still have some utility
    if mode == "portal":
        return pv["portal"]
    return max(pv["portal"], pv["cash"], best_transfer(card)[1])


# ---------------------------------------------------------------- matching

def _rule_matches(rule: dict, txn: Txn) -> int:
    """Specificity score: 3 merchant match, 2 category match, 1 generic, 0 none."""
    if "merchants" in rule:
        return 3 if txn.merchant in rule["merchants"] else 0
    if "categories" in rule:
        return 2 if txn.category in rule["categories"] else 0
    return 1  # generic rule (e.g. spend threshold) applies to everything


def candidate_rules(card: dict, txn: Txn) -> list[dict]:
    scored = [(s, i, r) for i, r in enumerate(card.get("rules", [])) if (s := _rule_matches(r, txn))]
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [r for _, _, r in scored]


# ---------------------------------------------------------------- earning

def _take(points: float, cap: float | None, used: float) -> float:
    if cap is None:
        return points
    return max(0.0, min(points, cap - used))


def _earn_base(card: dict, amount: float, state: MonthState, pending: dict[str, float]) -> tuple[Segment | None, bool]:
    base = card["base"]
    raw = amount * base["rate"] / 100.0
    used = state.points_by_rule.get("base", 0.0) + pending.get("base", 0.0)
    got = _take(raw, base.get("cap"), used)
    pending["base"] = pending.get("base", 0.0) + got
    return Segment("base", "Base rate", amount, got), got + 1e-9 < raw


def compute_earn(card: dict, txn: Txn, state: MonthState | None = None, mode: str = "best") -> Earn:
    """Rewards for one transaction. Does NOT mutate `state`."""
    state = state or MonthState()
    notes: list[str] = []
    rules = candidate_rules(card, txn)
    specific = [r for r in rules if _rule_matches(r, txn) >= 2]

    if txn.category in card.get("exclusions", []) and not specific:
        return Earn(card["id"], 0.0, 0.0, [Segment("excluded", "Excluded category", txn.amount, 0.0)],
                    excluded=True, notes=[f"{txn.category.replace('_', ' ')} spends earn no rewards on this card"])

    segments: list[Segment] = []
    pending: dict[str, float] = {}
    remaining = txn.amount
    capped = False

    for rule in rules:
        if remaining <= 0:
            break
        amt = remaining
        threshold = rule.get("min_monthly_spend")
        if threshold:
            below = max(0.0, threshold - state.spend)
            if below >= amt:
                continue  # threshold not crossed by this txn
            if below > 0:
                # the part below the threshold is handled by later rules / base
                amt = amt - below
                notes.append(f"₹{below:,.0f} counts toward the ₹{threshold:,.0f} monthly threshold")
        raw = amt * rule["rate"] / 100.0
        used = state.points_by_rule.get(rule["id"], 0.0) + pending.get(rule["id"], 0.0)
        got = _take(raw, rule.get("cap"), used)
        if got <= 0 and rule.get("cap") is not None:
            capped = True
            notes.append(f"'{rule['label']}' monthly cap already reached")
            if rule.get("on_cap", "base") == "none":
                segments.append(Segment(rule["id"], rule["label"] + " (capped)", amt, 0.0))
                remaining -= amt
            continue
        consumed = amt if got >= raw - 1e-9 else got / rule["rate"] * 100.0
        pending[rule["id"]] = pending.get(rule["id"], 0.0) + got
        segments.append(Segment(rule["id"], rule["label"], consumed, got))
        remaining -= consumed
        if consumed < amt - 1e-9:
            capped = True
            notes.append(f"'{rule['label']}' cap hit mid-transaction")
            if rule.get("on_cap", "base") == "none":
                segments.append(Segment(rule["id"], rule["label"] + " (capped)", amt - consumed, 0.0))
                remaining -= amt - consumed

    if remaining > 1e-9:
        seg, base_capped = _earn_base(card, remaining, state, pending)
        segments.append(seg)
        if base_capped:
            capped = True
            notes.append("Base-rate monthly cap reached")

    points = sum(s.points for s in segments)
    value = points * point_value(card, mode)
    return Earn(card["id"], round(points, 2), round(value, 2), segments, capped=capped, notes=notes)


def apply_earn(state: MonthState, txn: Txn, earn: Earn) -> None:
    state.spend += txn.amount
    for s in earn.segments:
        if s.points:
            state.points_by_rule[s.rule_id] = state.points_by_rule.get(s.rule_id, 0.0) + s.points


def simulate(card: dict, txns: list[Txn], mode: str = "best", state: MonthState | None = None) -> tuple[list[Earn], MonthState]:
    """Replay a month of transactions in order, respecting caps."""
    state = state.copy() if state else MonthState()
    out = []
    for t in txns:
        e = compute_earn(card, t, state, mode)
        apply_earn(state, t, e)
        out.append(e)
    return out, state


# ---------------------------------------------------------------- annual

def milestone_value(card: dict, annual_spend: float, mode: str = "best") -> tuple[float, list[dict]]:
    total, hit = 0.0, []
    pv = point_value(card, mode)
    for m in card.get("milestones", []):
        if annual_spend >= m["annual_spend"]:
            v = m.get("points", 0) * pv + m.get("voucher_inr", 0)
            total += v
            hit.append({**m, "value": round(v, 2)})
    return total, hit


def effective_fee(card: dict, annual_spend: float) -> float:
    w = card.get("fee_waiver_spend")
    if w is not None and annual_spend >= w:
        return 0.0
    return float(card.get("annual_fee", 0))
