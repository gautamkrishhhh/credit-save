"""Sage -- the conversational assistant.

Pipeline: utterance -> intent classifier + entity extractor -> dialogue
policy (with short-term context for follow-ups like "what about 5000?")
-> tool call into the real engines -> grounded natural-language answer plus
structured data the UI renders as rich cards. Every number Sage says comes
from the rewards engine, never from a template.
"""
from __future__ import annotations

import json

from ..core.db import Database
from ..data.cards import get_card
from ..data.offers import OFFERS
from ..data.partners import PARTNERS
from ..data.taxonomy import CATEGORIES, merchant_name
from ..ml.nlu import Entities, IntentClassifier, extract
from .insights import insights
from .recommend import best_card, compare, discover, missed_savings, offer_discount
from .redeem import goal_plan, milestones, redemption_options
from .wallet import card_summary, month_bounds, value_mode

SUGGESTIONS = ["Which card for Swiggy ₹800?", "How much are my points worth?", "Suggest a new card",
               "Compare Atlas vs Infinia", "Missed savings", "Forecast my spending"]


def rs(v: float) -> str:
    return f"₹{v:,.0f}"


class Sage:
    def __init__(self, db: Database, clf: IntentClassifier):
        self.db, self.clf = db, clf

    # ------------------------------------------------------------- context
    def _ctx(self) -> dict:
        try:
            return json.loads(self.db.get_setting("chat_ctx", "{}") or "{}")
        except json.JSONDecodeError:
            return {}

    def _save_ctx(self, intent: str, e: Entities) -> None:
        self.db.set_setting("chat_ctx", json.dumps({"intent": intent, "merchant": e.merchant, "category": e.category,
                                                    "amount": e.amount, "cards": e.cards, "partner": e.partner}))

    # ------------------------------------------------------------- entry
    def respond(self, text: str) -> dict:
        text = text.strip()
        wal = self.db.list_user_cards()
        e = extract(text, wal)
        intent, conf, top = self.clf.predict(text)
        ctx = self._ctx()

        # dialogue policy: resolve low-confidence / elliptical follow-ups
        words = len(text.split())
        if (e.merchant or e.category) and intent in ("greeting", "thanks", "help", "offers") and conf < 0.6:
            intent = "best_card"
        if (e.amount and words <= 4 and not e.cards and ctx.get("intent") == "best_card"
                and intent not in ("goal", "points_value", "redeem") and conf < 0.9):
            intent = "best_card"  # elliptical follow-up: "what about 3000?"
        if conf < 0.45:
            if e.merchant or e.category:
                intent = "best_card"
            elif e.amount and words <= 4 and ctx.get("intent") in ("best_card",):
                intent = "best_card"
            elif len(e.cards) >= 2:
                intent = "compare"
            elif len(e.cards) == 1:
                intent = "card_info"
        if intent == "best_card" and not (e.merchant or e.category) and ctx.get("intent") == "best_card":
            e.merchant, e.category = ctx.get("merchant"), ctx.get("category")
        if intent == "best_card" and e.amount is None and ctx.get("intent") == "best_card" and words <= 4 \
                and (e.merchant, e.category) == (ctx.get("merchant"), ctx.get("category")):
            e.amount = ctx.get("amount")
        if intent == "compare" and len(e.cards) == 1 and ctx.get("cards"):
            e.cards = list(dict.fromkeys(ctx["cards"] + e.cards))
        if intent == "goal" and not e.partner and ctx.get("partner"):
            e.partner = ctx["partner"]

        handler = getattr(self, f"_h_{intent}", self._h_help)
        try:
            out = handler(e, text)
        except Exception as ex:  # never crash the chat
            out = {"text": f"Sorry, I hit a problem answering that ({ex}). Try rephrasing?"}
        self._save_ctx(intent, e)
        out.setdefault("data", None)
        out.setdefault("suggestions", SUGGESTIONS[:4])
        out.update({"intent": intent, "confidence": conf, "top_intents": top, "entities": e.__dict__})
        self.db.add_chat("user", text)
        self.db.add_chat("assistant", out["text"], {k: out[k] for k in ("intent", "confidence", "data", "suggestions")})
        return out

    # ------------------------------------------------------------- handlers
    def _need_wallet(self) -> dict | None:
        if not self.db.list_user_cards():
            return {"text": "You haven't added any cards yet. Add your cards in **My Cards** (or load demo data) and ask me again.",
                    "suggestions": ["Suggest a new card", "Tell me about Axis Atlas"]}
        return None

    def _h_best_card(self, e: Entities, text: str) -> dict:
        if w := self._need_wallet():
            return w
        if not (e.merchant or e.category):
            return {"text": "Where are you spending? e.g. *“Swiggy ₹600”*, *“flights 25k”* or *“fuel”*.",
                    "suggestions": ["Swiggy 600", "Amazon 5000", "Flights 25000", "Fuel 2000"]}
        amount = e.amount or 1000
        r = best_card(self.db, amount, e.merchant, e.category)
        b = r["best"]
        where = r["merchant_name"] or r["category_name"]
        lines = [f"For **{rs(amount)}** on **{where}**, use **{b['name']}** → {rs(b['total_value'])} back "
                 f"(**{b['effective_pct']}%**, via {b['rule']})."]
        if b["offer"]:
            lines.append(f"Includes offer: *{b['offer']['title']}* (−{rs(b['offer_value'])}).")
        if len(r["ranked"]) > 1:
            rest = ", ".join(f"{x['name']} {x['effective_pct']}%" for x in r["ranked"][1:4])
            lines.append(f"Others: {rest}.")
        for x in r["ranked"]:
            if x["capped"] and x["notes"]:
                lines.append(f"⚠️ {x['name']}: {x['notes'][0]}.")
                break
        if s := r["not_owned_suggestion"]:
            lines.append(f"💡 Not in your wallet: **{s['name']}** would give {s['effective_pct']}% (+{rs(s['extra_value'])}).")
        if not e.amount:
            lines.append("_(Assumed ₹1,000 — tell me the amount for exact numbers.)_")
        return {"text": "\n".join(lines), "data": {"type": "best_card", **r},
                "suggestions": [f"What about {rs(amount * 5).replace('₹', '₹')}?", "Any offers on " + where, "Missed savings"]}

    def _h_points_value(self, e: Entities, text: str) -> dict:
        if w := self._need_wallet():
            return w
        r = redemption_options(self.db)
        cards = [c for c in r["cards"] if not e.cards or c["card_id"] in e.cards]
        lines = [f"Your rewards are worth **{rs(r['totals']['best'])}** at best value "
                 f"({rs(r['totals']['cash'])} as cash)."]
        for c in cards:
            if c["balance"]:
                lines.append(f"• **{c['name']}**: {c['balance']:,.0f} {c['currency']} → up to {rs(c['best']['value'])} ({c['best']['type']})")
        for c in cards:
            if c["expiring"]:
                lines.append(f"⏳ {c['name']} points expire in **{c['expiring']['days']} days**!")
        return {"text": "\n".join(lines), "data": {"type": "redeem", **r}, "suggestions": ["How should I redeem?", "I need 60000 KrisFlyer miles"]}

    def _h_redeem(self, e: Entities, text: str) -> dict:
        if w := self._need_wallet():
            return w
        r = redemption_options(self.db)
        cards = [c for c in r["cards"] if c["balance"] and (not e.cards or c["card_id"] in e.cards)]
        if not cards:
            return {"text": "No point balances to redeem yet. Update balances in **My Cards**."}
        lines = []
        for c in cards:
            top = c["options"][:3]
            lines.append(f"**{c['name']}** ({c['balance']:,.0f} {c['currency']}):")
            for o in top:
                lines.append(f"  • {o['type']} — {rs(o['value'])} ({o['per_point']:.2f}/pt)")
            if c["uplift_vs_worst"] > 0:
                lines.append(f"  Best option is worth {rs(c['uplift_vs_worst'])} more than the worst.")
        return {"text": "\n".join(lines), "data": {"type": "redeem", **r}}

    def _h_goal(self, e: Entities, text: str) -> dict:
        if w := self._need_wallet():
            return w
        if not e.partner:
            names = ", ".join(p["name"] for p in list(PARTNERS.values())[:6])
            return {"text": f"Which programme? e.g. {names}."}
        target = next((n for n in e.numbers if n >= 100), None)
        if not target:
            return {"text": f"How many {PARTNERS[e.partner]['name']} points do you need?"}
        g = goal_plan(self.db, e.partner, target)
        if not g["steps"]:
            return {"text": f"None of your cards transfer to {g['partner_name']}. Cards that do: " +
                    ", ".join(c for c in _cards_for_partner(e.partner)) + "."}
        lines = [f"Plan for **{target:,.0f} {g['partner_name']}** points:"]
        for s in g["steps"]:
            lines.append(f"• Transfer {s['transfer_card_points']:,} pts from **{s['card']}** ({s['ratio']}) → {s['partner_points']:,}")
        lines.append("✅ Goal reachable today." if g["complete"] else f"❗ Short by {g['shortfall']:,} points — keep earning on your transfer cards.")
        return {"text": "\n".join(lines), "data": {"type": "goal", **g}}

    def _h_discover(self, e: Entities, text: str) -> dict:
        d = discover(self.db, top=5)
        recs = d["recommendations"]
        if e.cards:
            target = next((r for r in recs if r["card"]["id"] == e.cards[0]), None)
            if target is None:
                full = discover(self.db, top=100)["recommendations"]
                target = next((r for r in full if r["card"]["id"] == e.cards[0]), None)
            if target:
                v = target["incremental_value"]
                verdict = "✅ Worth it" if v > 1000 else ("🤏 Marginal" if v > 0 else "❌ Not worth it")
                return {"text": f"{verdict}: adding **{target['card']['name']}** changes your yearly net rewards by **{rs(v)}** "
                                f"(after its {rs(target['fee'])} fee). " + " ".join(target["why"][:2]),
                        "data": {"type": "discover", **d}}
        lines = [f"Based on your ~{rs(d['monthly_spend'])}/month spend ({d['profile_source']} profile), top picks:"]
        for i, r in enumerate(recs[:3], 1):
            lines.append(f"{i}. **{r['card']['name']}** — +{rs(r['incremental_value'])}/yr net. {'; '.join(r['why'][:2])}")
        if d["best_pair"]:
            lines.append(f"Starting fresh? Best 2-card combo: **{' + '.join(d['best_pair']['cards'])}** ≈ {rs(d['best_pair']['annual_net'])}/yr.")
        return {"text": "\n".join(lines), "data": {"type": "discover", **d}}

    def _h_compare(self, e: Entities, text: str) -> dict:
        if len(e.cards) < 2:
            return {"text": "Name two cards to compare, e.g. *“Atlas vs Infinia”*."}
        c = compare(self.db, e.cards[:3])
        cs = c["cards"]
        lines = [f"On your spend profile (yearly net):"]
        for x in sorted(cs, key=lambda x: -x["annual_net_on_profile"]):
            lines.append(f"• **{x['name']}**: {rs(x['annual_net_on_profile'])} · fee {rs(x['annual_fee'])} · base {x['base_return_pct']}% · lounges {x['lounge']['domestic']}/{x['lounge']['international']}")
        win = max(cs, key=lambda x: x["annual_net_on_profile"])
        lines.append(f"🏆 **{win['name']}** wins for you.")
        return {"text": "\n".join(lines), "data": {"type": "compare", **c}}

    def _h_card_info(self, e: Entities, text: str) -> dict:
        if not e.cards:
            return {"text": "Which card? e.g. *“Tell me about Axis Atlas”*."}
        card = get_card(e.cards[0])
        s = card_summary(card, value_mode(self.db))
        fee = f"{rs(s['annual_fee'])}" + (f" (waived at {rs(s['fee_waiver_spend'])}/yr)" if s["fee_waiver_spend"] else "")
        lines = [f"**{s['name']}** ({s['issuer']}, {s['network']})",
                 f"• Fee: {fee} · Min income ~{s['min_income_lpa']} LPA",
                 f"• Base return: **{s['base_return_pct']}%** · Up to {s['top_return_pct']}% · 1 {s['reward_currency']} ≈ ₹{s['value_per_point']}"]
        for r in s["rules"]:
            lines.append(f"• {r['label']}" + (f" (cap {r['cap']:,}/mo)" if r["cap"] else ""))
        lines.append(f"• Lounges: {s['lounge']['domestic']} domestic / {s['lounge']['international']} intl · Forex {s['forex_markup']}%")
        if s["exclusions"]:
            lines.append("• No rewards on: " + ", ".join(CATEGORIES.get(x, x) for x in s["exclusions"]))
        if s["best_transfer"]:
            lines.append(f"• Best transfer: {PARTNERS[s['best_transfer']]['name']} (≈₹{s['best_transfer_value']}/pt)")
        return {"text": "\n".join(lines), "data": {"type": "card", "card": s},
                "suggestions": [f"Should I get {s['name']}?", "Suggest a new card"]}

    def _h_spend_summary(self, e: Entities, text: str) -> dict:
        start, end = month_bounds()
        txns = [t for t in self.db.list_transactions(start, end) if not t["is_refund"]]
        if e.merchant or e.category:
            f = [t for t in txns if (e.merchant and t["merchant"] == e.merchant) or (not e.merchant and t["category"] == e.category)]
            label = merchant_name(e.merchant) or CATEGORIES.get(e.category, e.category)
            return {"text": f"This month you've spent **{rs(sum(t['amount'] for t in f))}** on {label} across {len(f)} transactions."}
        by = {}
        for t in txns:
            by[t["category"]] = by.get(t["category"], 0) + t["amount"]
        top = sorted(by.items(), key=lambda kv: -kv[1])[:5]
        lines = [f"This month: **{rs(sum(by.values()))}** across {len(txns)} transactions."]
        lines += [f"• {CATEGORIES[c]}: {rs(v)}" for c, v in top]
        return {"text": "\n".join(lines), "data": {"type": "spend", "by_category": by}}

    def _h_missed(self, e: Entities, text: str) -> dict:
        if w := self._need_wallet():
            return w
        start, end = month_bounds()
        from datetime import date
        ytd = missed_savings(self.db, f"{date.today().year}-01-01", end)
        m = missed_savings(self.db, start, end)
        lines = [f"This year you earned **{rs(ytd['earned'])}** but could have earned **{rs(ytd['optimal'])}** "
                 f"→ efficiency **{ytd['efficiency_pct']}%** (missed {rs(ytd['missed'])}). This month: {rs(m['missed'])} missed."]
        for x in ytd["top_misses"][:4]:
            lines.append(f"• {x['date']} {x['merchant']} {rs(x['amount'])}: used {x['used']}, **{x['better']}** would give +{rs(x['missed'])}")
        return {"text": "\n".join(lines), "data": {"type": "missed", **ytd}}

    def _h_milestones(self, e: Entities, text: str) -> dict:
        if w := self._need_wallet():
            return w
        ms = milestones(self.db)
        if e.user_cards:
            ms = [m for m in ms if m["user_card_id"] in e.user_cards] or ms
        if not ms:
            return {"text": "None of your cards have spend-based milestones or fee waivers."}
        lines = []
        for c in ms:
            lines.append(f"**{c['name']}** — {rs(c['spend_12m'])} in last 12 months (projected {rs(c['projected_annual'])}):")
            for m in c["milestones"]:
                status = "✅" if m["achieved"] else ("🟢 on track" if m["on_track"] else f"needs {rs(m['remaining'])} more")
                lines.append(f"  • {m['label']}: {m['pct']}% {status}")
        return {"text": "\n".join(lines), "data": {"type": "milestones", "items": ms}}

    def _h_offers(self, e: Entities, text: str) -> dict:
        ucs = self.db.list_user_cards()
        found = []
        for o in OFFERS:
            if e.merchant and o.get("merchant") != e.merchant:
                continue
            for uc in ucs:
                card = get_card(uc["card_id"])
                amt = max(o.get("min_txn", 0), 1)
                d, off = offer_discount(card, o.get("merchant"), o.get("category"), amt * 2,
                                        _next_valid_day(o))
                if off and off["id"] == o["id"]:
                    found.append((o, uc["nickname"] or card["name"]))
                    break
        if not found:
            where = f" on {merchant_name(e.merchant)}" if e.merchant else ""
            return {"text": f"No active offers{where} for your cards right now."}
        lines = ["Offers on your cards:"] + [f"• **{o['title']}** — {name} (min {rs(o.get('min_txn', 0))}, till {o['valid_till']})" for o, name in found[:8]]
        return {"text": "\n".join(lines), "data": {"type": "offers", "offers": [o for o, _ in found]}}

    def _h_forecast(self, e: Entities, text: str) -> dict:
        ins = insights(self.db)
        fc = ins["forecast"]
        if not fc["categories"]:
            return {"text": "I need at least a month of transactions to forecast. Add some or load demo data."}
        if e.category and e.category in fc["categories"]:
            f = fc["categories"][e.category]
            return {"text": f"Next month {CATEGORIES[e.category].lower()}: **{rs(f['point'])}** (80% range {rs(f['lower'])}–{rs(f['upper'])})."}
        t = fc["total"]
        top = sorted(fc["categories"].items(), key=lambda kv: -kv[1]["point"])[:5]
        lines = [f"Forecast for next month: **{rs(t['point'])}** (80% range {rs(t['lower'])}–{rs(t['upper'])}), Holt trend model."]
        lines += [f"• {CATEGORIES[c]}: {rs(f['point'])}" + (" ↑" if f["trend"] > 0 else " ↓" if f["trend"] < 0 else "") for c, f in top]
        if ins["tips"]:
            lines.append("💡 " + ins["tips"][0]["text"])
        return {"text": "\n".join(lines), "data": {"type": "forecast", **fc}}

    def _h_anomaly(self, e: Entities, text: str) -> dict:
        an = insights(self.db)["anomalies"]
        if not an:
            return {"text": "Nothing unusual — all transactions look consistent with your patterns. ✅"}
        lines = [f"I flagged **{len(an)}** unusual transaction(s):"]
        for t in an[:5]:
            lines.append(f"• {t['txn_date']} {merchant_name(t['merchant']) or t['description']} {rs(t['amount'])} — {t['reason'] or 'unusual pattern'}")
        return {"text": "\n".join(lines), "data": {"type": "anomalies", "items": an}}

    def _h_greeting(self, e: Entities, text: str) -> dict:
        n = len(self.db.list_user_cards())
        return {"text": f"Hi! I'm **Sage** 🦉 — your credit card co-pilot. You have {n} card(s) in your wallet. "
                        "Ask me which card to use, what your points are worth, or which card to get next.",
                "suggestions": SUGGESTIONS}

    def _h_help(self, e: Entities, text: str) -> dict:
        return {"text": "I can help with:\n• **Which card to use** — “Swiggy ₹800”, “flights 30k”\n• **Points value & redemption** — “what are my points worth?”\n"
                        "• **Transfer goals** — “I need 60k KrisFlyer miles”\n• **New card advice** — “suggest a card”, “should I get Magnus?”\n"
                        "• **Compare** — “Atlas vs Infinia”\n• **Spending** — summary, forecast, unusual transactions, missed savings, milestones, offers",
                "suggestions": SUGGESTIONS}

    def _h_thanks(self, e: Entities, text: str) -> dict:
        return {"text": "Happy to help! Happy saving 💰"}


def _next_valid_day(offer: dict):
    """Offers list should show day-restricted offers too, so test on a day they run."""
    from datetime import date, timedelta
    d = date.today()
    while "weekdays" in offer and d.weekday() not in offer["weekdays"]:
        d += timedelta(days=1)
    return d


def _cards_for_partner(pid: str) -> list[str]:
    from ..data.cards import CARDS
    return [c["name"] for c in CARDS if pid in c.get("transfer", {})]
