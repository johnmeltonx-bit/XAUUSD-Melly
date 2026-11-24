import os
import time
from flask import Flask, jsonify, make_response
from analyzer import analyse
from feed import get_market_data, FeedError

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

# Inline page deliberately avoids template lookup errors when a folder is omitted on GitHub.
PAGE = r'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>XAUUSD Smart Analyser</title>
<style>body{margin:0;padding:18px;background:#101722;color:#edf2f7;font:16px Arial}.wrap{max-width:900px;margin:auto}.card{background:#1b2736;border:1px solid #344255;border-radius:12px;padding:16px;margin:12px 0}h1{font-size:24px}.muted{color:#aab8c8}.big{font-size:30px;font-weight:bold}button{padding:12px 18px;border:0;border-radius:8px;background:#d5a94c;color:#111;font-weight:bold}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px}.value{font-size:20px;font-weight:bold}li{margin:9px 0;line-height:1.4}</style></head><body><div class="wrap"><h1>XAUUSD Smart Analyser</h1><p class="muted">JustMarkets XAUUSD.m · Signal-only · No trade execution</p><div class="card"><div id="feed">Checking data connection…</div><p><button onclick="loadData()">Analyse now</button></p></div><div class="card"><div id="signal" class="big">WAIT</div><p id="score"></p><div id="levels" class="grid"></div></div><div class="card"><h3>Why this decision?</h3><ul id="reasons"><li>Waiting for verified data.</li></ul></div><p class="muted">Refreshes every 30 seconds. Signals are analytical conditions, not guarantees. Verify the live chart, spread and execution price yourself.</p></div>
<script>async function loadData(){try{const r=await fetch('/api/analyse',{cache:'no-store'});const d=await r.json();const f=d.feed||{};document.getElementById('feed').innerHTML=f.connected?`<b>LIVE FEED CONNECTED</b><br>Provider: ${f.provider}<br>Broker symbol: ${f.symbol}<br>Bid: ${f.bid} | Ask: ${f.ask} | Spread: ${f.spread}<br>Quote age: ${f.quote_age_ms} ms<br>Source time: ${f.timestamp}`:`<b>LIVE FEED NOT CONNECTED</b><br>${(d.reasons||[]).join(' ')}`;document.getElementById('signal').textContent=d.signal||'WAIT';document.getElementById('score').textContent=d.score===undefined?'':`Evidence score: ${d.score}/${d.max_score}`;let items=[];if(d.entry_reference!==undefined){items=[['Entry reference',d.entry_reference],['Entry zone',(d.entry_zone||[]).join(' – ')],['Stop loss',d.stop_loss],...Object.entries(d.take_profit||{})];}document.getElementById('levels').innerHTML=items.map(x=>`<div class="card"><div class="muted">${x[0]}</div><div class="value">${x[1]}</div></div>`).join('');document.getElementById('reasons').innerHTML=(d.reasons||['No analysis available.']).map(x=>`<li>${x}</li>`).join('');}catch(e){document.getElementById('feed').textContent='Dashboard request failed: '+e;}}loadData();setInterval(loadData,30000);</script></body></html>'''

@app.get("/")
def home():
    response = make_response(PAGE)
    response.headers["Cache-Control"] = "no-store"
    return response

@app.get("/health")
def health():
    return jsonify({"ok": True, "service": "xauusd-smart-analyser", "mode": "read-only"})

@app.get("/api/analyse")
def api_analyse():
    try:
        data, quote, feed_meta = get_market_data()
        result = analyse(data, quote)
        result["feed"] = {"connected": True, "provider": "xauapi JustMarkets feed",
                          "symbol": quote.get("broker_symbol", "XAUUSD.m"),
                          "bid": quote.get("bid"), "ask": quote.get("ask"),
                          "spread": quote.get("spread"), "timestamp": quote.get("timestamp"),
                          "quote_age_ms": feed_meta["quote_age_ms"], "meta": feed_meta}
        return jsonify(result)
    except FeedError as exc:
        return jsonify({"status": "FEED DISCONNECTED", "signal": "WAIT", "feed": {"connected": False},
                        "reasons": [str(exc), "No entry, stop-loss or take-profit is generated without verified fresh broker data."]}), 503
    except Exception as exc:
        app.logger.exception("Unhandled analysis error")
        return jsonify({"status": "INTERNAL ERROR", "signal": "WAIT", "feed": {"connected": False},
                        "reasons": [f"Internal application error: {type(exc).__name__}. Check Render logs."]}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
