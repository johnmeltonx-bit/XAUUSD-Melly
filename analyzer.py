from statistics import mean
from datetime import datetime

REQUIRED = {"M1": 40, "M5": 20, "M15": 20, "H1": 10}


def _num(c, key):
    v = float(c[key])
    if not (v == v and abs(v) != float("inf")):
        raise ValueError("non-finite OHLC value")
    return v


def validate_candles(candles, tf):
    if not isinstance(candles, list) or len(candles) < REQUIRED[tf]:
        raise ValueError(f"Not enough completed {tf} candles (need {REQUIRED[tf]}, got {len(candles) if isinstance(candles, list) else 0}).")
    for c in candles:
        o, h, l, cl = (_num(c, k) for k in ("open", "high", "low", "close"))
        if h < max(o, l, cl) or l > min(o, h, cl):
            raise ValueError(f"Invalid OHLC candle in {tf} data.")


def swings(candles, n=2):
    highs, lows = [], []
    for i in range(n, len(candles) - n):
        h, lo = _num(candles[i], "high"), _num(candles[i], "low")
        if all(h > _num(candles[j], "high") for j in range(i-n, i)) and all(h >= _num(candles[j], "high") for j in range(i+1, i+n+1)):
            highs.append((i, h))
        if all(lo < _num(candles[j], "low") for j in range(i-n, i)) and all(lo <= _num(candles[j], "low") for j in range(i+1, i+n+1)):
            lows.append((i, lo))
    return highs, lows


def structure(candles):
    hs, ls = swings(candles)
    if len(hs) < 2 or len(ls) < 2:
        return "NEUTRAL", hs, ls
    bullish = hs[-1][1] > hs[-2][1] and ls[-1][1] > ls[-2][1]
    bearish = hs[-1][1] < hs[-2][1] and ls[-1][1] < ls[-2][1]
    return ("BULLISH" if bullish else "BEARISH" if bearish else "RANGING"), hs, ls


def atr(candles, period=14):
    tr = []
    for i in range(1, len(candles)):
        hi, lo = _num(candles[i], "high"), _num(candles[i], "low")
        prev = _num(candles[i-1], "close")
        tr.append(max(hi-lo, abs(hi-prev), abs(lo-prev)))
    return mean(tr[-period:]) if tr else 0.0


def liquidity_sweep(candles, lookback=12):
    if len(candles) < lookback + 1:
        return None
    previous, last = candles[-lookback-1:-1], candles[-1]
    old_high = max(_num(c, "high") for c in previous)
    old_low = min(_num(c, "low") for c in previous)
    if _num(last, "high") > old_high and _num(last, "close") < old_high:
        return {"type": "BUY-SIDE LIQUIDITY SWEEP", "level": old_high, "direction": "BEARISH"}
    if _num(last, "low") < old_low and _num(last, "close") > old_low:
        return {"type": "SELL-SIDE LIQUIDITY SWEEP", "level": old_low, "direction": "BULLISH"}
    return None


def fair_value_gaps(candles):
    found = []
    for i in range(2, len(candles)):
        left, right = candles[i-2], candles[i]
        if _num(right, "low") > _num(left, "high"):
            found.append({"type": "BULLISH FVG", "low": _num(left, "high"), "high": _num(right, "low"), "index": i})
        elif _num(right, "high") < _num(left, "low"):
            found.append({"type": "BEARISH FVG", "low": _num(right, "high"), "high": _num(left, "low"), "index": i})
    return found


def analyse(data, quote):
    reasons = []
    try:
        for tf, minimum in REQUIRED.items():
            validate_candles(data.get(tf), tf)
    except (ValueError, TypeError, KeyError) as exc:
        return {"status": "NO TRADE", "signal": "WAIT", "reasons": [str(exc)], "score": 0, "max_score": 10}

    h1, m15, m5, m1 = (data[k] for k in ("H1", "M15", "M5", "M1"))
    h1_bias, _, _ = structure(h1)
    m15_bias, _, _ = structure(m15)
    m5_bias, _, _ = structure(m5)
    m1_bias, _, _ = structure(m1)
    reasons.extend([f"H1 structure: {h1_bias}.", f"M15 structure: {m15_bias}.",
                    f"M5 structure: {m5_bias}.", f"M1 structure: {m1_bias}."])

    direction = "BUY" if h1_bias == "BULLISH" else "SELL" if h1_bias == "BEARISH" else None
    expected = "BULLISH" if direction == "BUY" else "BEARISH" if direction == "SELL" else None
    score = 2 if direction else 0
    if not direction:
        reasons.append("H1 has no confirmed directional structure.")
    if direction and m15_bias == expected:
        score += 2
        reasons.append("M15 agrees with the H1 directional bias.")
    else:
        reasons.append("M15 does not confirm H1 direction.")
    if direction and m5_bias == expected:
        score += 2
        reasons.append("M5 confirms the setup direction.")
    else:
        reasons.append("M5 confirmation is missing or conflicting.")

    sweep = liquidity_sweep(m15)
    if sweep and direction and sweep["direction"] == expected:
        score += 2
        reasons.append(f"{sweep['type']} detected at {sweep['level']:.2f}.")
    else:
        reasons.append("No aligned M15 liquidity sweep confirmed.")

    fvg = [x for x in fair_value_gaps(m5)[-6:] if x["type"] == ("BULLISH FVG" if direction == "BUY" else "BEARISH FVG")] if direction else []
    if fvg:
        score += 1
        z = fvg[-1]
        reasons.append(f"Aligned M5 fair value gap: {z['low']:.2f}–{z['high']:.2f}.")
    else:
        reasons.append("No recent aligned M5 fair value gap.")

    if direction and m1_bias == expected:
        score += 1
        reasons.append("M1 structure agrees with the proposed direction.")
    else:
        reasons.append("M1 entry trigger is not aligned.")

    if not direction or score < 7 or m15_bias != expected or m5_bias != expected or m1_bias != expected:
        reasons.append("Entry criteria are incomplete. No trade is recommended.")
        return {"status": "NO TRADE", "signal": "WAIT", "score": score, "max_score": 10,
                "reasons": reasons, "data_quality": "FRESH_BROKER_DATA"}

    bid, ask = float(quote["bid"]), float(quote["ask"])
    spread = ask - bid
    if bid <= 0 or ask < bid or spread < 0:
        return {"status": "NO TRADE", "signal": "WAIT", "score": score,
                "reasons": reasons + ["Broker quote values are invalid."], "data_quality": "INVALID_QUOTE"}
    entry = ask if direction == "BUY" else bid
    volatility = atr(m1)
    if volatility <= 0:
        return {"status": "NO TRADE", "signal": "WAIT", "score": score,
                "reasons": reasons + ["ATR is unavailable; protective levels cannot be calculated."]}
    if spread > volatility * 0.20:
        return {"status": "NO TRADE", "signal": "WAIT", "score": score,
                "reasons": reasons + [f"Spread ({spread:.2f}) is too large relative to M1 ATR ({volatility:.2f})."]}

    window = m1[-30:]
    if direction == "BUY":
        sl = min(_num(c, "low") for c in window) - 0.15 * volatility
        risk = entry - sl
        if risk <= 0:
            return {"status": "NO TRADE", "signal": "WAIT", "reasons": reasons + ["Stop calculation invalid."]}
        tps = {"TP1_2R": entry + 2*risk, "TP2_3R": entry + 3*risk, "TP3_5R": entry + 5*risk}
    else:
        sl = max(_num(c, "high") for c in window) + 0.15 * volatility
        risk = sl - entry
        if risk <= 0:
            return {"status": "NO TRADE", "signal": "WAIT", "reasons": reasons + ["Stop calculation invalid."]}
        tps = {"TP1_2R": entry - 2*risk, "TP2_3R": entry - 3*risk, "TP3_5R": entry - 5*risk}

    reasons.extend([f"Entry reference uses broker {('ask' if direction == 'BUY' else 'bid')} price.",
                    f"Stop is placed beyond the recent 30-candle M1 extreme with a 0.15 ATR buffer ({volatility:.2f}).",
                    "Targets are mathematical 2R, 3R and 5R planning levels, not predictions or guaranteed exits.",
                    "Recheck spread and price before any manual execution."])
    return {"status": "SETUP DETECTED", "signal": direction, "score": score, "max_score": 10,
            "entry_reference": round(entry, 2), "entry_zone": [round(entry-0.10*volatility, 2), round(entry+0.10*volatility, 2)],
            "stop_loss": round(sl, 2), "take_profit": {k: round(v, 2) for k, v in tps.items()},
            "risk_distance": round(risk, 2), "spread": round(spread, 2), "reasons": reasons,
            "data_quality": "FRESH_BROKER_DATA"}
