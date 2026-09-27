# Architecture: from low level to high level

```
 ┌──────────────────────────────────────────────────────────────────┐
 │ L5  UI           frontend/  vanilla-JS SPA, hash router, SVG charts│
 ├──────────────────────────────────────────────────────────────────┤
 │ L4  API          app/main.py  FastAPI, pydantic validation         │
 ├──────────────────────────────────────────────────────────────────┤
 │ L3  Services     app/services/  wallet · recommend (optimizer)     │
 │                  redeem · ingest · insights · assistant (Sage)     │
 ├───────────────────────────────┬──────────────────────────────────┤
 │ L2  ML / NLP  app/ml/         │ L2  Persistence  app/core/db.py   │
 │  categorizer · sms_parser     │  raw sqlite3, versioned           │
 │  nlu · anomaly · forecast     │  migrations, WAL, indexes         │
 ├───────────────────────────────┴──────────────────────────────────┤
 │ L1  Rewards engine   app/core/rewards.py  (pure functions, no I/O) │
 ├──────────────────────────────────────────────────────────────────┤
 │ L0  Domain data  app/data/  cards · merchants/categories ·         │
 │                  transfer partners · offers                        │
 └──────────────────────────────────────────────────────────────────┘
```

## L0: domain data (`app/data`)
Everything is declarative. A card is a dict with a `base` rate and a list of `rules`. Each rule matches on `merchants` or `categories`, and can carry a `rate` in points per ₹100, a monthly `cap`, an `on_cap` behaviour and a `min_monthly_spend` threshold. A card also has `exclusions`, `point_value` (cash / portal), `transfer` ratios and `milestones`. You add a card by adding data, with no code change.

## L1: rewards engine (`core/rewards.py`)
`compute_earn(card, txn, month_state)` is a pure function:
1. It picks candidate rules by specificity: merchant (3) beats category (2), which beats generic threshold rules (1).
2. Excluded categories earn nothing unless a specific rule overrides the exclusion.
3. For each rule, it consumes as much of the amount as the remaining cap allows. The overflow falls through to the next rule or the base rate, or earns nothing when `on_cap == "none"`.
4. Threshold rules split a single transaction: the part below the month-to-date threshold gets the lower rate, and the rest gets the higher rate.
5. The base rate can have its own cap.

`MonthState` is rebuilt by **replaying** the month's transactions in order (`simulate` / `wallet.month_states`). Caps are therefore always exact and never drift, because no "points used" counter is persisted.

Valuation (`point_value`) supports three modes: `cash`, `portal` and `best`. `best` takes the maximum of portal, cash and ratio × partner value.

## L2: persistence (`core/db.py`)
Plain `sqlite3`, using `PRAGMA user_version` migrations, WAL mode, foreign keys and indexes on `(user_card_id, txn_date)`. There is a small repository API: parameterised SQL only, with allow-listed columns for updates.

## L2: ML / NLP (`app/ml`)
- **categorizer.py**: a two-stage hybrid. First a deterministic alias resolver (word-boundary regexes, longest alias first) finds the exact `merchant_id` the engine needs. If that fails, a TF-IDF char+word model with logistic regression predicts the category. The synthetic corpus renders every alias through 15 bank-descriptor templates (`POS 4411 SWIGGY*BLR`, `UPI/…`, `PAYU*…`). It also composes random proper nouns with category **cue words** ("Madhav *Fuels*", "Sai *Medicals*"), so the model learns cues that transfer to unseen merchants. Evaluation uses GroupShuffleSplit by merchant/phrase: the naïve split scored 100% because of leakage, while the grouped split gives an honest 72%. User corrections are added to the training data with a 5× weight on retrain.
- **sms_parser.py**: precision-first regexes for the common Indian card alert formats (amount, last-4, merchant, date across 12 formats, bank, refunds).
- **nlu.py**: the intent classifier plus entity extraction. Card names are matched **first and masked out**, so "Flipkart Axis" isn't read as the merchant Flipkart. Amounts understand k, lakh and crore. Merchants fall back to difflib fuzzy matching for typos.
- **forecast.py**: Holt's method (level + trend) implemented directly, with α and β chosen by grid search on one-step-ahead SSE. Intervals come from the residual standard deviation.
- **anomaly.py**: an Isolation Forest over 6 engineered features, gated by a robust per-category z-score. Categories with little history use a global z-score instead.

## L3: services
- **wallet**: joins the catalogue with the user's cards and computes month state, cap usage and valuations.
- **recommend**:
  - `best_card` ranks wallet cards, applies offers and suggests a card you don't own when it would do better.
  - `missed_savings` does a chronological replay comparing the card used with the best card at that moment.
  - `optimize` is the portfolio optimizer. Spend is chunked. Buckets with the highest achievable rate are served first, so scarce capped accelerators go where they matter most. Each chunk goes to the card with the highest *marginal* value. Results are annualised with milestones and fee waivers.
  - `discover` computes the incremental value of adding each catalogue card, and searches for the best 2-card combination.
  - `spend_profile` averages the last 3 months per merchant bucket, rescaled per category by the ML forecast.
- **redeem**: ranks redemption options, plans transfer goals (cheapest opportunity cost first) and tracks milestones and fee waivers with a run-rate projection.
- **ingest**: the pipeline that turns SMS or manual input into merchant, category, card match, persisted row and anomaly re-score.
- **assistant (Sage)**: intent plus entities feed a dialogue policy. Low-confidence or elliptical follow-ups reuse the stored context (`chat_ctx`). A handler then calls a real service and returns grounded text plus structured data.

## L4/L5: API and UI
The API is a thin FastAPI layer (`create_app` factory, so tests get an isolated in-memory DB). Models train in a background thread at startup, and the UI shows "ML engine training…" until they're ready. The SPA has no build step and no external requests: charts are hand-written SVG, and it supports dark mode and mobile widths.

## Verification loop
`tests/` covers each layer: engine (L1), ML (L2), services (L3) and API (L4). `scripts/e2e.mjs` drives the real server in headless Chromium through every screen. It fails on any JS error or error panel, or on horizontal overflow on mobile, and saves screenshots. `scripts/verify.sh --loop N` repeats the whole cycle.
