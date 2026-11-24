import os
import time
from datetime import datetime, timezone
import requests

BASE_URL = "https://api.xauapi.com"
TIMEOUT = 12

class FeedError(RuntimeError):
    pass


def _request(path, params=None):
    key = os.getenv("XAUAPI_KEY", "").strip()
    if not key:
        raise FeedError("Live data is not configured. Add a valid XAUAPI_KEY in Render Environment.")
    try:
        response = requests.get(BASE_URL + path, params=params or {"feed": "justmarkets"},
                                headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
                                timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise FeedError(f"Market-data connection failed: {exc.__class__.__name__}.") from exc
    if response.status_code == 401:
        raise FeedError("Data API rejected the key (401). Check XAUAPI_KEY.")
    if response.status_code == 403:
        raise FeedError("Data API access is not active (403). Check subscription entitlement.")
    if response.status_code == 429:
        raise FeedError("Data API rate or annual quota limit reached (429).")
    if response.status_code == 503:
        raise FeedError("JustMarkets market feed or candle history is unavailable (503).")
    if not response.ok:
        raise FeedError(f"Data API returned HTTP {response.status_code}.")
    try:
        return response.json()
    except ValueError as exc:
        raise FeedError("Data API returned invalid JSON.") from exc


def _fresh(received_at, max_age_ms, label):
    try:
        age = int(time.time() * 1000) - int(received_at)
    except (TypeError, ValueError):
        raise FeedError(f"{label} has no valid receipt timestamp.")
    if age < -1000 or age > max_age_ms:
        raise FeedError(f"{label} is stale or timestamp-invalid (age {age} ms).")
    return age


def _parse_timestamp(value):
    if not value:
        raise FeedError("A candle is missing its source timestamp.")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception as exc:
        raise FeedError("A candle has an invalid timestamp.") from exc


def _aggregate_h1(m15):
    # Align by UTC hour; only build H1 bars from four consecutive completed M15 bars.
    buckets = {}
    for c in m15:
        dt = _parse_timestamp(c.get("timestamp"))
        hour = dt.replace(minute=0, second=0, microsecond=0)
        buckets.setdefault(hour, []).append((dt, c))
    result = []
    for hour in sorted(buckets):
        items = sorted(buckets[hour], key=lambda x: x[0])
        if len(items) != 4:
            continue
        mins = [x[0].minute for x in items]
        if mins != [0, 15, 30, 45]:
            continue
        bars = [x[1] for x in items]
        result.append({"timestamp": hour.isoformat(), "open": float(bars[0]["open"]),
                       "high": max(float(x["high"]) for x in bars),
                       "low": min(float(x["low"]) for x in bars),
                       "close": float(bars[-1]["close"]), "complete": True})
    return result


def get_market_data():
    status = _request("/v1/status", {"feed": "justmarkets"})
    if status.get("status") != "available" or status.get("stale") is True:
        raise FeedError("JustMarkets feed status is not available/fresh.")
    quote = _request("/v1/quote", {"feed": "justmarkets"})
    if quote.get("stale") is True:
        raise FeedError("Latest JustMarkets quote is stale.")
    quote_age = _fresh(quote.get("received_at"), 5000, "Broker quote")
    if not quote.get("timestamp"):
        raise FeedError("Broker quote has no source timestamp.")

    data = {}
    candle_ages = {}
    for tf in ("M1", "M5", "M15"):
        payload = _request("/v1/candles", {"feed": "justmarkets", "interval": tf})
        if payload.get("stale") is True:
            raise FeedError(f"{tf} candle snapshot is stale.")
        candle_ages[tf] = _fresh(payload.get("received_at"), 30000, f"{tf} candles")
        candles = payload.get("candles")
        if not isinstance(candles, list):
            raise FeedError(f"{tf} endpoint returned no candle array.")
        data[tf] = [c for c in candles if c.get("complete") is True]
        data[tf].sort(key=lambda x: _parse_timestamp(x.get("timestamp")))
    data["H1"] = _aggregate_h1(data["M15"])
    return data, quote, {"status": status.get("status"), "quote_age_ms": quote_age,
                         "candle_receipt_age_ms": candle_ages, "source": status.get("source"),
                         "collector": status.get("collector"), "sampled": status.get("sampled")}
