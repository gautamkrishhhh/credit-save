# 🦉 CreditSage

A personal, self-hosted credit-card rewards co-pilot for India, built as a feature-for-feature clone of **SaveSage**. It runs entirely on your machine: no accounts, no cloud, and your data stays in a local SQLite file.

## Features

| Feature | What it does |
|---|---|
| **Which card should I use?** | Ranks every card in your wallet for a purchase. It accounts for merchant accelerators, category rates, monthly caps you've **already used this month**, excluded categories and live card offers. It also tells you when a card you don't own would do better. |
| **Ask Sage (AI assistant)** | Answers questions in plain English: "Swiggy ₹800", "what about 3000?", "Atlas vs Infinia", "I need 60k KrisFlyer miles", "should I get Magnus?". Every number comes from the rewards engine. |
| **Rewards dashboard** | Total points value (cash / portal / best transfer), month spend and rewards, card-choice efficiency, missed savings, expiring points and milestone progress. |
| **My Cards (vault)** | Add from a 20-card catalogue with balances, last-4 digits and expiry dates. Shows per-card cap usage and value per point. |
| **Transactions** | Manual entry with live ML categorisation. You can **paste bank SMS alerts** to import them, with automatic card matching by last-4. Recategorising a transaction teaches the model. |
| **Rewards & redeem** | Every redemption option ranked by ₹ value, including transfer partners. There's also a **transfer-goal planner** (which cards to move to KrisFlyer, Marriott and others) and a milestone / fee-waiver tracker. |
| **Discover cards** | A portfolio optimizer that calculates how much each new card would add to **your** wallet each year, after fees, milestones and caps. It also finds the best 2-card combo. |
| **Compare** | Compares 2–3 cards side by side, including net value on your own spend profile and return % by category. |
| **Offers** | Card-linked offers filtered to your wallet. Offers are also factored into "Which card?". |
| **Insights & ML** | A next-month spend forecast with prediction intervals, unusual-transaction detection, smart tips and live model metrics. |

## Run it

```bash
pip install -r requirements.txt
python run.py                 # → http://localhost:8000
```

Click **Load demo** in the sidebar to explore with a realistic wallet and 6 months of spending, or **Reset** to start with your own cards.

## Verify it (the loop)

```bash
python -m pytest -q tests     # 67 tests: engine → ML → services → API
scripts/verify.sh             # tests + boots the server + drives every screen in headless Chromium + screenshots
scripts/verify.sh --loop 3    # repeat the whole thing 3×
```

## ML engine

| Model | Technique | Honest metric |
|---|---|---|
| Transaction categorizer | Alias-based merchant resolver, falling back to TF-IDF (char 2–5 + word 1–2 grams) → logistic regression. Trained on a synthetic corpus of noisy bank descriptors plus your corrections. | **72% accuracy on merchants never seen in training** (GroupShuffleSplit by merchant). |
| Sage intent classifier | TF-IDF (word + char) → logistic regression over 16 intents, plus entity extraction (amounts like "5k" or "1.2 lakh", cards, fuzzy merchants, categories, partners) and a dialogue policy with follow-up context. | **20/20 on hand-written paraphrases** never seen in training. |
| Spend forecaster | Holt linear exponential smoothing written in numpy, with α and β fitted per category by grid search and 80% prediction intervals. | Recovers linear trends to within 3% in tests. |
| Anomaly detector | Isolation Forest over engineered features, plus a robust (median/MAD) z-score and a check for rare categories. | Flags planted outliers only, in tests. |
| Card optimizer | Cap-aware greedy allocation of a spend profile across cards, annualised with milestones and fee waivers. | Splits spend exactly at the reward caps, in tests. |

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the layer-by-layer design.

> ⚠️ Card reward structures, partner valuations and offers are **simplified approximations** for personal use. Verify them with your issuer. Edit `backend/app/data/*.py` to match your cards exactly.
