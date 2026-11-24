# XAUUSD Smart Analyser — fixed build

Read-only signal dashboard for JustMarkets XAUUSD.m. It never sends, modifies or closes orders.

## Data connection

The live-data adapter uses the documented xauapi JustMarkets feed (`https://api.xauapi.com`). It is an independent data provider, not an official JustMarkets service. It requires an active API subscription and private API key. Create the key in the provider workspace and add it to Render as the secret environment variable `XAUAPI_KEY`. Never put the key in GitHub or in frontend code.

Without the key, the homepage and `/health` still load; `/api/analyse` returns WAIT with a clear feed-disconnected reason. The app does not generate fake/live-looking prices.

Provider documentation says the JustMarkets feed returns M1/M5/M15 OHLC, quote and status; candles are marked complete and freshness must be checked. H1 is aggregated from four complete M15 bars aligned to UTC hour boundaries.

**Cost warning:** Provider pricing page currently lists Pro at USD 149/month, billed annually (USD 1,788/year). Do not subscribe unless you knowingly accept this cost. This project does not include a free JustMarkets live feed.

## Deploy on Render

1. Upload the *contents* of this folder to the top level of the GitHub repository. `app.py`, `analyzer.py`, `feed.py`, `requirements.txt` and `render.yaml` must be at repository root.
2. In Render use Blueprint deploy from `render.yaml`, or create a Python web service with build command `pip install -r requirements.txt` and start command `gunicorn --workers 1 --threads 4 --timeout 60 app:app`.
3. Add `XAUAPI_KEY` in Render → Environment. Do not commit it.
4. Verify `/health` returns `{"ok":true,...}`. Open `/` for dashboard. If the key is missing/invalid, dashboard still loads and clearly says feed disconnected.

## Local tests

`python -m unittest discover -s tests -v`

## Signal rules

H1 direction, M15 setup, M5 confirmation, M1 trigger; liquidity sweep and aligned M5 FVG add evidence. Output is BUY/SELL only when strict alignment and minimum evidence are present; otherwise WAIT. Entry uses ask for BUY and bid for SELL; SL is beyond recent M1 structure with ATR buffer; TP levels are mathematical 2R/3R/5R. This is not proof of profitability. Backtest and demo-forward-test before risking money.
