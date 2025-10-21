#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BTC FOOTPRINT ORDERFLOW - VERSIONE COMPLETA
Box body completo con bordi colorati + 45 candele + zoom dinamico
"""

from flask import Flask, jsonify, request
import time
import requests
from collections import defaultdict
from datetime import datetime
import threading

app = Flask(__name__)

SYMBOL_BINANCE = "BTCUSDT"
CACHE_TTL = 60

CACHE = {
    'data': {},
    'lock': threading.Lock()
}

def get_interval_ms(interval):
    intervals = {"1m": 60000, "5m": 300000, "15m": 900000, "30m": 1800000, "1h": 3600000}
    return intervals.get(interval, 60000)

def fetch_with_retry(url, params, max_retries=3, timeout=15):
    """Fetch con retry automatico"""
    for attempt in range(max_retries):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.Timeout:
            print(f"[WARN] Timeout tentativo {attempt + 1}/{max_retries}")
            if attempt < max_retries - 1:
                time.sleep(1)
            else:
                print("[ERROR] Timeout dopo tutti i tentativi")
                return []
        except Exception as e:
            print(f"[ERROR] {e}")
            return []
    return []

def fetch_klines(interval, limit=150):
    """Scarica candele con retry"""
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": SYMBOL_BINANCE, "interval": interval, "limit": limit}
    return fetch_with_retry(url, params, max_retries=3, timeout=15)

def fetch_trades(start_ms, end_ms):
    """Scarica trade con retry"""
    url = "https://api.binance.com/api/v3/aggTrades"
    params = {"symbol": SYMBOL_BINANCE, "startTime": start_ms, "endTime": end_ms, "limit": 1000}
    return fetch_with_retry(url, params, max_retries=2, timeout=12)

def round_price(price, step):
    return round(price / step) * step

def process_data(interval, step):
    klines = fetch_klines(interval, limit=150)
    if not klines:
        print("[WARN] Nessuna candela ricevuta")
        return {"bars": [], "stats": {"error": "Timeout API Binance"}}

    bars = []
    interval_ms = get_interval_ms(interval)
    total_volume = 0
    total_delta = 0

    for i, k in enumerate(klines):
        ts = int(k[0])
        o, h, l, c = float(k[1]), float(k[2]), float(k[3]), float(k[4])
        vol = float(k[5])

        open_rounded = round_price(o, step)
        close_rounded = round_price(c, step)
        high_rounded = round_price(h, step)
        low_rounded = round_price(l, step)

        bid_vol = defaultdict(float)
        ask_vol = defaultdict(float)
        
        if i >= len(klines) - 20:
            trades = fetch_trades(ts, ts + interval_ms - 1)
            for t in trades:
                price = round_price(float(t['p']), step)
                qty = float(t['q'])
                if low_rounded <= price <= high_rounded:
                    if t['m']:
                        bid_vol[price] += qty
                    else:
                        ask_vol[price] += qty

        active_prices = set()
        for price in bid_vol.keys():
            active_prices.add(price)
        for price in ask_vol.keys():
            active_prices.add(price)
        active_prices.add(open_rounded)
        active_prices.add(close_rounded)
        
        sorted_prices = sorted(active_prices, reverse=True)

        levels_data = []
        bar_total_bid = sum(bid_vol.values())
        bar_total_ask = sum(ask_vol.values())
        
        for price_level in sorted_prices:
            bid = bid_vol.get(price_level, 0)
            ask = ask_vol.get(price_level, 0)
            
            is_in_body = False
            if open_rounded < close_rounded:
                is_in_body = open_rounded <= price_level <= close_rounded
            else:
                is_in_body = close_rounded <= price_level <= open_rounded
            
            levels_data.append({
                "price": price_level,
                "bid": round(bid, 2),
                "ask": round(ask, 2),
                "significant": (bid + ask) > max((bar_total_bid + bar_total_ask) * 0.12, 0.1),
                "in_body": is_in_body
            })

        bar_delta = bar_total_ask - bar_total_bid
        total_volume += vol
        total_delta += bar_delta

        bars.append({
            "timestamp": ts,
            "time": datetime.fromtimestamp(ts/1000).strftime("%H:%M"),
            "open": round(o, 2),
            "high": round(h, 2),
            "low": round(l, 2),
            "close": round(c, 2),
            "open_rounded": open_rounded,
            "close_rounded": close_rounded,
            "volume": round(vol, 2),
            "levels": levels_data,
            "bullish": c > o,
            "delta": round(bar_delta, 2)
        })

    stats = {
        "price": bars[-1]["close"] if bars else 0,
        "volume": round(total_volume, 2),
        "delta": round(total_delta, 2),
        "bars_count": len(bars)
    }

    return {"bars": bars, "stats": stats}

@app.route('/')
def index():
    html = """
<!DOCTYPE html>
<html>
<head>
    <title>BTC Footprint - Complete</title>
    <meta charset="utf-8">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: Arial; background: #0a0a0a; color: #e0e0e0; overflow: hidden; }
        .header { background: #1a1a1a; padding: 8px 15px; border-bottom: 1px solid #333; display: flex; justify-content: space-between; }
        .header h1 { font-size: 14px; color: #00d4ff; }
        .controls { display: flex; gap: 8px; }
        .controls select, .controls button { background: #2a2a2a; color: #e0e0e0; border: 1px solid #444; padding: 4px 8px; border-radius: 3px; font-size: 11px; cursor: pointer; }
        .controls button { background: #00d4ff; color: #000; font-weight: 600; }
        .controls button.active { background: #26a69a; }
        .stats-bar { background: #1a1a1a; padding: 5px 15px; border-bottom: 1px solid #333; display: flex; gap: 15px; font-size: 10px; }
        .stat-item { display: flex; gap: 5px; }
        .stat-label { color: #888; }
        .stat-value { color: #00d4ff; font-weight: 600; }
        .stat-value.positive { color: #26a69a; }
        .stat-value.negative { color: #ef5350; }
        .navigation { background: #1a1a1a; padding: 8px 15px; border-bottom: 1px solid #333; display: flex; gap: 10px; align-items: center; }
        .navigation button { background: #2a2a2a; color: #e0e0e0; border: 1px solid #444; padding: 5px 15px; border-radius: 3px; cursor: pointer; font-size: 11px; }
        .navigation button:hover { background: #3a3a3a; }
        .navigation input[type="range"] { flex: 1; max-width: 400px; }
        .zoom-controls { display: flex; gap: 8px; align-items: center; margin-left: 20px; }
        .zoom-slider { width: 120px; }
        .zoom-label { font-size: 10px; color: #888; min-width: 70px; }
        .zoom-reset { background: #444; color: #e0e0e0; border: 1px solid #666; padding: 3px 8px; border-radius: 3px; cursor: pointer; font-size: 10px; }
        .zoom-reset:hover { background: #555; }
        .chart-container { height: calc(100vh - 130px); overflow: auto; padding: 10px; background: #0a0a0a; }
        .footprint-table { border-collapse: collapse; transition: all 0.2s ease-out; }
        .bar-column { border: 1px solid #1a1a1a; padding: 0; vertical-align: top; position: relative; }
        .time-header { background: #1a1a1a; padding: 5px; text-align: center; border-bottom: 2px solid #333; position: sticky; top: 0; z-index: 10; }
        .time-text { font-weight: 600; margin-bottom: 2px; color: #00d4ff; }
        .ohlc-text { color: #666; }
        .price-cell { background: #0a0a0a; padding: 1px; position: relative; }
        
        /* Box completo per body - bordi su tutti i lati */
        .price-cell.in-body {
            border-left: 2px solid rgba(76, 175, 80, 0.7) !important;
            border-right: 2px solid rgba(76, 175, 80, 0.7) !important;
        }
        
        .price-cell.in-body.bullish {
            border-left-color: rgba(76, 175, 80, 0.7) !important;
            border-right-color: rgba(76, 175, 80, 0.7) !important;
            background: rgba(76, 175, 80, 0.06) !important;
        }
        
        .price-cell.in-body.bearish {
            border-left-color: rgba(244, 67, 54, 0.7) !important;
            border-right-color: rgba(244, 67, 54, 0.7) !important;
            background: rgba(244, 67, 54, 0.06) !important;
        }
        
        /* Bordo superiore del box (OPEN) */
        .price-cell.open-level {
            border-top: 3px solid #4caf50 !important;
        }
        
        .price-cell.open-level.bearish {
            border-top: 3px solid #f44336 !important;
        }
        
        /* Bordo inferiore del box (CLOSE) */
        .price-cell.close-level {
            border-bottom: 3px solid #4caf50 !important;
        }
        
        .price-cell.close-level.bearish {
            border-bottom: 3px solid #f44336 !important;
        }
        
        .price-cell-content { display: flex; justify-content: space-between; gap: 1px; height: 100%; }
        .bid-value, .ask-value { flex: 1; text-align: center; border-radius: 2px; display: flex; align-items: center; justify-content: center; }
        .bid-value { background: rgba(239, 83, 80, 0.12); color: #ef5350; }
        .ask-value { background: rgba(38, 166, 154, 0.12); color: #26a69a; }
        .bid-value.significant { background: rgba(239, 83, 80, 0.35); font-weight: 700; box-shadow: 0 0 4px rgba(239,83,80,0.5); }
        .ask-value.significant { background: rgba(38, 166, 154, 0.35); font-weight: 700; box-shadow: 0 0 4px rgba(38,166,154,0.5); }
        .price-label { position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%); color: #555; pointer-events: none; z-index: 1; }
        .delta-footer { background: #1a1a1a; padding: 4px; text-align: center; border-top: 2px solid #333; }
        .delta-value { font-weight: 700; }
        .delta-value.positive { color: #26a69a; }
        .delta-value.negative { color: #ef5350; }
        .loading { position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%); background: rgba(0,0,0,0.9); padding: 15px 30px; border-radius: 5px; z-index: 1000; display: none; }
        .loading.active { display: block; }
        .error-msg { color: #f44336; text-align: center; padding: 20px; }
        .refresh-info { font-size: 9px; color: #888; margin-left: 10px; }
        ::-webkit-scrollbar { width: 5px; height: 5px; }
        ::-webkit-scrollbar-track { background: #0a0a0a; }
        ::-webkit-scrollbar-thumb { background: #333; }
    </style>
</head>
<body>
    <div class="header">
        <h1>🔥 BTC Footprint <span class="refresh-info" id="refreshInfo">Auto-refresh: OFF</span></h1>
        <div class="controls">
            <select id="interval" onchange="loadData()">
                <option value="1m" selected>1m</option>
                <option value="5m">5m</option>
                <option value="15m">15m</option>
                <option value="30m">30m</option>
                <option value="1h">1h</option>
            </select>
            <select id="step" onchange="loadData()">
                <option value="5">5$</option>
                <option value="10" selected>10$</option>
                <option value="25">25$</option>
                <option value="50">50$</option>
            </select>
            <button onclick="loadData()">↻ Aggiorna</button>
            <button id="autoRefreshBtn" onclick="toggleAutoRefresh()">🔄 Auto</button>
        </div>
    </div>
    <div class="stats-bar" id="stats-bar"></div>
    <div class="navigation">
        <button onclick="scrollBars(-10)">◄◄</button>
        <button onclick="scrollBars(-1)">◄</button>
        <input type="range" id="rangeSlider" min="0" max="100" value="100" oninput="updateRange(this.value)">
        <span id="rangeLabel">Posizione</span>
        <button onclick="scrollBars(1)">►</button>
        <button onclick="scrollBars(10)">►►</button>
        <button onclick="resetView()">Reset</button>
        <div class="zoom-controls">
            <span class="zoom-label" id="zoomLabel">Zoom: 100%</span>
            <input type="range" id="zoomSlider" class="zoom-slider" min="50" max="150" value="100" oninput="applyDynamicZoom(this.value)">
            <button class="zoom-reset" onclick="resetZoom()">Reset Zoom</button>
        </div>
    </div>
    <div class="loading" id="loading">⏳ Caricamento...</div>
    <div class="chart-container" id="chart-container"></div>
    <script>
        let currentData = null;
        let viewStart = 0;
        let viewCount = 45;  // Aumentato a 45 candele
        let autoRefreshInterval = null;
        let currentZoom = 100;
        
        const refreshIntervals = {
            '1m': 15000, '5m': 30000, '15m': 60000, '30m': 60000, '1h': 60000
        };
        
        function getRefreshInterval() {
            return refreshIntervals[document.getElementById('interval').value] || 30000;
        }
        
        function applyDynamicZoom(value) {
            currentZoom = value;
            document.getElementById('zoomLabel').textContent = `Zoom: ${value}%`;
            
            const scale = value / 100;
            const baseRowHeight = 22;
            const baseColWidth = 70;
            const baseFontSize = 8;
            const basePriceFont = 7;
            const baseTimeFont = 10;
            const baseOhlcFont = 7;
            const baseDeltaFont = 9;
            const baseBorderWidth = 3;
            
            const rowHeight = Math.round(baseRowHeight * scale);
            const colWidth = Math.round(baseColWidth * scale);
            const fontSize = Math.max(6, Math.round(baseFontSize * scale));
            const priceFont = Math.max(5, Math.round(basePriceFont * scale));
            const timeFont = Math.max(8, Math.round(baseTimeFont * scale));
            const ohlcFont = Math.max(6, Math.round(baseOhlcFont * scale));
            const deltaFont = Math.max(7, Math.round(baseDeltaFont * scale));
            const borderWidth = Math.max(2, Math.round(baseBorderWidth * scale));
            
            const style = document.createElement('style');
            style.id = 'dynamic-zoom-style';
            const existingStyle = document.getElementById('dynamic-zoom-style');
            if (existingStyle) existingStyle.remove();
            
            style.textContent = `
                .price-row { height: ${rowHeight}px !important; }
                .bar-column { min-width: ${colWidth}px !important; max-width: ${colWidth}px !important; }
                .bid-value, .ask-value { font-size: ${fontSize}px !important; padding: ${Math.max(1, Math.round(3 * scale))}px ${Math.max(1, Math.round(1 * scale))}px !important; }
                .price-label { font-size: ${priceFont}px !important; }
                .time-text { font-size: ${timeFont}px !important; }
                .ohlc-text { font-size: ${ohlcFont}px !important; }
                .delta-value { font-size: ${deltaFont}px !important; }
                .price-cell.open-level { border-top-width: ${borderWidth}px !important; }
                .price-cell.close-level { border-bottom-width: ${borderWidth}px !important; }
            `;
            
            document.head.appendChild(style);
        }
        
        function resetZoom() {
            currentZoom = 100;
            document.getElementById('zoomSlider').value = 100;
            applyDynamicZoom(100);
        }
        
        function toggleAutoRefresh() {
            const btn = document.getElementById('autoRefreshBtn');
            const info = document.getElementById('refreshInfo');
            
            if (autoRefreshInterval) {
                clearInterval(autoRefreshInterval);
                autoRefreshInterval = null;
                btn.classList.remove('active');
                info.textContent = 'Auto-refresh: OFF';
            } else {
                const refreshTime = getRefreshInterval();
                autoRefreshInterval = setInterval(loadData, refreshTime);
                btn.classList.add('active');
                info.textContent = `Auto-refresh: ${refreshTime/1000}s`;
            }
        }
        
        function loadData() {
            document.getElementById('loading').classList.add('active');
            const interval = document.getElementById('interval').value;
            const step = document.getElementById('step').value;
            
            if (autoRefreshInterval) {
                const refreshTime = getRefreshInterval();
                document.getElementById('refreshInfo').textContent = `Auto-refresh: ${refreshTime/1000}s`;
            }
            
            fetch(`/api/data?interval=${interval}&step=${step}`)
                .then(r => r.json())
                .then(data => {
                    if (data.bars.length === 0) {
                        document.getElementById('chart-container').innerHTML = '<div class="error-msg">❌ Errore: timeout API. Riprova.</div>';
                        document.getElementById('loading').classList.remove('active');
                        return;
                    }
                    currentData = data;
                    renderStatsBar(data.stats);
                    resetView();
                    document.getElementById('loading').classList.remove('active');
                })
                .catch(e => {
                    console.error(e);
                    document.getElementById('chart-container').innerHTML = '<div class="error-msg">❌ Errore di connessione.</div>';
                    document.getElementById('loading').classList.remove('active');
                });
        }
        
        function renderStatsBar(stats) {
            const deltaClass = stats.delta >= 0 ? 'positive' : 'negative';
            const deltaSign = stats.delta >= 0 ? '+' : '';
            document.getElementById('stats-bar').innerHTML = `
                <div class="stat-item"><span class="stat-label">Prezzo:</span><span class="stat-value">$${stats.price.toLocaleString()}</span></div>
                <div class="stat-item"><span class="stat-label">Volume:</span><span class="stat-value">${stats.volume.toFixed(2)}</span></div>
                <div class="stat-item"><span class="stat-label">Delta:</span><span class="stat-value ${deltaClass}">${deltaSign}${stats.delta.toFixed(2)}</span></div>
                <div class="stat-item"><span class="stat-label">Barre:</span><span class="stat-value">${stats.bars_count}</span></div>
            `;
        }
        
        function resetView() {
            if (!currentData) return;
            viewStart = Math.max(0, currentData.bars.length - viewCount);
            document.getElementById('rangeSlider').max = Math.max(0, currentData.bars.length - viewCount);
            document.getElementById('rangeSlider').value = viewStart;
            renderChart();
        }
        
        function scrollBars(delta) {
            if (!currentData) return;
            viewStart = Math.max(0, Math.min(currentData.bars.length - viewCount, viewStart + delta));
            document.getElementById('rangeSlider').value = viewStart;
            renderChart();
        }
        
        function updateRange(value) {
            viewStart = parseInt(value);
            renderChart();
        }
        
        function renderChart() {
            if (!currentData || currentData.bars.length === 0) return;
            const displayBars = currentData.bars.slice(viewStart, viewStart + viewCount);
            document.getElementById('rangeLabel').textContent = `${viewStart + 1}-${viewStart + displayBars.length}/${currentData.bars.length}`;
            
            let allPrices = new Set();
            displayBars.forEach(bar => {
                bar.levels.forEach(level => {
                    if (level.bid > 0 || level.ask > 0 || level.price === bar.open_rounded || level.price === bar.close_rounded) {
                        allPrices.add(level.price);
                    }
                });
            });
            const sortedPrices = Array.from(allPrices).sort((a, b) => b - a);
            
            let html = '<table class="footprint-table"><tr>';
            displayBars.forEach(bar => {
                html += `<td class="bar-column time-header">
                    <div class="time-text">${bar.time}</div>
                    <div class="ohlc-text">O:${bar.open}<br>H:${bar.high}<br>L:${bar.low}<br>C:${bar.close}</div>
                </td>`;
            });
            html += '</tr>';
            
            sortedPrices.forEach(price => {
                html += '<tr class="price-row">';
                displayBars.forEach(bar => {
                    const level = bar.levels.find(l => l.price === price);
                    const isOpen = bar.open_rounded === price;
                    const isClose = bar.close_rounded === price;
                    const barType = bar.bullish ? 'bullish' : 'bearish';
                    const inBody = level ? level.in_body : false;
                    
                    let cellClass = 'bar-column price-cell';
                    if (inBody) cellClass += ` in-body ${barType}`;
                    if (isOpen) cellClass += ` open-level ${barType}`;
                    if (isClose) cellClass += ` close-level ${barType}`;
                    
                    if (level && (level.bid > 0 || level.ask > 0)) {
                        const bidClass = level.significant && level.bid > 0 ? 'significant' : '';
                        const askClass = level.significant && level.ask > 0 ? 'significant' : '';
                        html += `<td class="${cellClass}">
                            <div class="price-cell-content">
                                <div class="bid-value ${bidClass}">${level.bid > 0 ? level.bid.toFixed(1) : ''}</div>
                                <div class="ask-value ${askClass}">${level.ask > 0 ? level.ask.toFixed(1) : ''}</div>
                            </div>
                            <div class="price-label">${price}</div>
                        </td>`;
                    } else {
                        html += `<td class="${cellClass}"><div class="price-label">${price}</div></td>`;
                    }
                });
                html += '</tr>';
            });
            
            html += '<tr>';
            displayBars.forEach(bar => {
                const deltaClass = bar.delta >= 0 ? 'positive' : 'negative';
                const deltaSign = bar.delta >= 0 ? '+' : '';
                html += `<td class="bar-column delta-footer">
                    <div class="delta-value ${deltaClass}">${deltaSign}${bar.delta.toFixed(1)}</div>
                </td>`;
            });
            html += '</tr></table>';
            document.getElementById('chart-container').innerHTML = html;
        }
        
        document.addEventListener('wheel', function(e) {
            if (e.ctrlKey) {
                e.preventDefault();
                const delta = e.deltaY > 0 ? -5 : 5;
                let newZoom = currentZoom + delta;
                newZoom = Math.max(50, Math.min(150, newZoom));
                document.getElementById('zoomSlider').value = newZoom;
                applyDynamicZoom(newZoom);
            }
        }, { passive: false });
        
        loadData();
    </script>
</body>
</html>
    """
    return html

@app.route('/api/data')
def get_data():
    interval = request.args.get('interval', '1m')
    step = float(request.args.get('step', 10))
    cache_key = f"{interval}_{step}"
    
    with CACHE['lock']:
        if cache_key in CACHE['data']:
            entry = CACHE['data'][cache_key]
            if time.time() - entry['timestamp'] < CACHE_TTL:
                print(f"[INFO] Cache hit per {cache_key}")
                return jsonify(entry['data'])
        
        print(f"[INFO] Fetching nuovi dati per {cache_key}...")
        data = process_data(interval, step)
        CACHE['data'][cache_key] = {'data': data, 'timestamp': time.time()}
        print(f"[INFO] Dati salvati in cache")
    
    return jsonify(data)

if __name__ == '__main__':
    print("=" * 60)
    print("BTC FOOTPRINT - VERSIONE COMPLETA")
    print("=" * 60)
    print("✅ Box body completo con bordi colorati")
    print("✅ Background trasparente verde/rosso (6%)")
    print("✅ 45 candele visualizzate")
    print("✅ Zoom dinamico 50%-150%")
    print("✅ Auto-refresh intelligente")
    print("=" * 60)
    print("http://localhost:5000")
    print("=" * 60)
    app.run(debug=True, host='0.0.0.0', port=5000, threaded=True)
