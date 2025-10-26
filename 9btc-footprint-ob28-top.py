#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BTC FOOTPRINT ORDERFLOW - v9
Layout Orizzontale Stesso Lato: Bid e Ask affiancati da sinistra
"""

from flask import Flask, jsonify, request
import time
import requests
from collections import defaultdict
from datetime import datetime
import threading

app = Flask(__name__)

SYMBOL_BINANCE = "BTCUSDT"
CACHE = {'data': {}, 'orderbook': {}, 'lock': threading.Lock()}

def get_interval_ms(interval):
    intervals = {"1m": 60000, "5m": 300000, "15m": 900000, "30m": 1800000, "1h": 3600000, "1d": 86400000}
    return intervals.get(interval, 60000)

def fetch_with_retry(url, params, max_retries=3, timeout=15):
    for attempt in range(max_retries):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                time.sleep(1)
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(1)
    return None

def fetch_klines(interval, limit=150):
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": SYMBOL_BINANCE, "interval": interval, "limit": limit}
    result = fetch_with_retry(url, params, max_retries=3, timeout=15)
    return result if result else []

def fetch_trades(start_ms, end_ms):
    url = "https://api.binance.com/api/v3/aggTrades"
    params = {"symbol": SYMBOL_BINANCE, "startTime": start_ms, "endTime": end_ms, "limit": 1000}
    result = fetch_with_retry(url, params, max_retries=2, timeout=12)
    return result if result else []

def fetch_orderbook():
    url = "https://api.binance.com/api/v3/depth"
    params = {"symbol": SYMBOL_BINANCE, "limit": 1000}
    result = fetch_with_retry(url, params, max_retries=2, timeout=10)
    return result if result else {"bids": [], "asks": []}

def round_price(price, step):
    return round(price / step) * step

def process_data(interval, step, update_last_only=False):
    klines = fetch_klines(interval, limit=150)
    if not klines:
        return {"bars": [], "stats": {"error": "Timeout API"}}

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
        
        should_calc_trades = False
        if update_last_only:
            should_calc_trades = (i == len(klines) - 1)  # CORRETTO: ultima candela!
        else:
            should_calc_trades = (i >= len(klines) - 20)
        
        if should_calc_trades:
            trades = fetch_trades(ts, ts + interval_ms - 1)
            if trades:
                for t in trades:
                    try:
                        price = round_price(float(t.get('p', 0)), step)
                        qty = float(t.get('q', 0))
                        if low_rounded <= price <= high_rounded:
                            if t.get('m'):
                                bid_vol[price] += qty
                            else:
                                ask_vol[price] += qty
                    except (ValueError, KeyError, TypeError):
                        continue

        active_prices = set()
        min_body = min(open_rounded, close_rounded)
        max_body = max(open_rounded, close_rounded)
        current_price = min_body
        while current_price <= max_body:
            active_prices.add(current_price)
            current_price += step
        
        for price in bid_vol.keys():
            active_prices.add(price)
        for price in ask_vol.keys():
            active_prices.add(price)
        
        sorted_prices = sorted(active_prices, reverse=True)

        levels_data = []
        bar_total_bid = sum(bid_vol.values())
        bar_total_ask = sum(ask_vol.values())
        
        for price_level in sorted_prices:
            bid = bid_vol.get(price_level, 0)
            ask = ask_vol.get(price_level, 0)
            
            is_in_body = close_rounded <= price_level <= open_rounded if open_rounded >= close_rounded else open_rounded <= price_level <= close_rounded
            
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
    html = r"""
<!DOCTYPE html>
<html>
<head>
    <title>BTC Footprint + Order Book Live v9</title>
    <meta charset="utf-8">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: Arial; background: #0a0a0a; color: #e0e0e0; margin: 0; padding: 0; height: 100vh; overflow: hidden; }
        .header { background: #1a1a1a; padding: 8px 15px; border-bottom: 1px solid #333; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; }
        .header h1 { font-size: 14px; color: #00d4ff; }
        .controls { display: flex; gap: 8px; }
        .controls select, .controls button { background: #2a2a2a; color: #e0e0e0; border: 1px solid #444; padding: 4px 8px; border-radius: 3px; font-size: 11px; cursor: pointer; }
        .controls button { background: #00d4ff; color: #000; font-weight: 600; }
        .controls button.active { background: #26a69a; }
        
        .ob-legend { display: flex; gap: 15px; font-size: 10px; }
        .ob-legend-item { display: flex; align-items: center; gap: 5px; }
        .ob-color-box { width: 12px; height: 12px; border-radius: 2px; }
        .ob-bid-color { background: rgba(76, 175, 80, 0.6); }
        .ob-ask-color { background: rgba(239, 83, 80, 0.6); }
        .ob-summary { display: flex; gap: 10px; align-items: center; font-size: 10px; color: #888; padding: 0 10px; border-left: 1px solid #333; }
        .ob-count { color: #00d4ff; font-weight: 600; }
        
        .stats-bar { background: #1a1a1a; padding: 5px 15px; border-bottom: 1px solid #333; display: flex; gap: 15px; font-size: 10px; flex-wrap: wrap; }
        .stat-item { display: flex; gap: 5px; align-items: center; }
        .stat-label { color: #888; }
        .stat-value { color: #00d4ff; font-weight: 600; }
        .stat-value.positive { color: #26a69a; }
        .stat-value.negative { color: #ef5350; }
        
        .navigation { background: #1a1a1a; padding: 8px 15px; border-bottom: 1px solid #333; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
        .navigation button { background: #2a2a2a; color: #e0e0e0; border: 1px solid #444; padding: 5px 15px; border-radius: 3px; cursor: pointer; font-size: 11px; }
        .navigation button:hover { background: #3a3a3a; }
        .navigation input[type="range"] { flex: 1; max-width: 400px; }
        .zoom-controls { display: flex; gap: 8px; align-items: center; margin-left: 20px; }
        .zoom-slider { width: 120px; }
        
        .chart-container { height: calc(100vh - 150px); overflow: auto; padding: 10px; background: #0a0a0a; }
        .footprint-table { border-collapse: collapse; width: auto; }
        .bar-column { 
            border: 1px solid #1a1a1a; 
            padding: 0; 
            vertical-align: top; 
            position: relative;
            width: 70px !important;
            min-width: 70px !important;
            max-width: 70px !important;
            display: table-cell;
        }
        .time-header { background: #1a1a1a; padding: 5px; text-align: center; border-bottom: 2px solid #333; position: sticky; top: 0; z-index: 10; height: auto; }
        .time-text { font-weight: 600; margin-bottom: 2px; color: #00d4ff; font-size: 10px; }
        .ohlc-text { color: #666; font-size: 7px; }
        
        .price-row { display: table-row; }
        .price-cell { 
            background: #0a0a0a; 
            padding: 0; 
            position: relative;
            height: 22px !important;
            min-height: 22px !important;
            max-height: 22px !important;
            display: table-cell;
            border: 1px solid #1a1a1a;
            width: 70px !important;
            overflow: hidden;
        }
        
        .orderbook-overlay { position: absolute; top: 0; left: 0; right: 0; bottom: 0; pointer-events: none; z-index: 0; }
        .ob-bid-bar { position: absolute; right: 0; height: 100%; background: rgba(76, 175, 80, 0.25); border-right: 2px solid rgba(76, 175, 80, 0.6); }
        .ob-ask-bar { position: absolute; right: 0; height: 100%; background: rgba(239, 83, 80, 0.25); border-right: 2px solid rgba(239, 83, 80, 0.6); }
        
        .price-cell.in-body { border-left: 2px solid rgba(76, 175, 80, 0.7) !important; border-right: 2px solid rgba(76, 175, 80, 0.7) !important; }
        .price-cell.in-body.bullish { background: rgba(76, 175, 80, 0.06) !important; }
        .price-cell.in-body.bearish { background: rgba(244, 67, 54, 0.06) !important; }
        .price-cell.open-level { border-top: 3px solid #4caf50 !important; }
        .price-cell.open-level.bearish { border-top: 3px solid #f44336 !important; }
        .price-cell.close-level { border-bottom: 3px solid #4caf50 !important; }
        .price-cell.close-level.bearish { border-bottom: 3px solid #f44336 !important; }
        
        .price-cell-content { display: flex; justify-content: flex-start; gap: 2px; height: 100%; position: relative; z-index: 1; padding-left: 2px; }
        .bid-value, .ask-value { text-align: center; display: flex; align-items: center; justify-content: center; font-size: 7px; padding: 0 3px; border-radius: 2px; }
        .bid-value { background: rgba(76, 175, 80, 0.15); color: #26a69a; }
        .ask-value { background: rgba(239, 83, 80, 0.15); color: #ef5350; margin-left: 2px; }
        .bid-value.significant { background: rgba(76, 175, 80, 0.4); font-weight: 700; }
        .ask-value.significant { background: rgba(239, 83, 80, 0.4); font-weight: 700; }
        .price-label { position: absolute; right: 2px; top: 50%; transform: translateY(-50%); color: #555; pointer-events: none; z-index: 2; font-size: 7px; }
        
        .delta-footer { background: #1a1a1a; padding: 4px; text-align: center; border-top: 2px solid #333; height: auto; }
        .delta-value { font-weight: 700; font-size: 9px; }
        .delta-value.positive { color: #26a69a; }
        .delta-value.negative { color: #ef5350; }
        
        .loading { position: fixed; top: 20px; right: 20px; transform: none; background: rgba(0,212,255,0.08); backdrop-filter: blur(2px); padding: 8px 16px; border-radius: 4px; z-index: 10000; display: none; color: #00d4ff; box-shadow: 0 0 12px rgba(0,212,255,0.4); pointer-events: none; border: 1px solid rgba(0,212,255,0.3); font-size: 11px; }
        .loading.active { display: block; }
        ::-webkit-scrollbar { width: 5px; }
        ::-webkit-scrollbar-track { background: #0a0a0a; }
        ::-webkit-scrollbar-thumb { background: #333; }
    
        .trading-signal { 
            position: fixed; 
            top: 100px; 
            left: 20px;
            width: 140px; 
            z-index: 999; 
            animation: pulse 2s ease-in-out infinite;
        }

        @keyframes pulse {
            0%, 100% { transform: scale(1); }
            50% { transform: scale(1.05); }
        }
        
        #chart-container {
            width: 100%;
            height: calc(100vh - 200px);
            background: #1a1a1a;
            position: relative;
            overflow-y: auto;
            overflow-x: auto;
            z-index: 1;
            scroll-behavior: smooth;
            padding-bottom: 180px;
            padding-right: 100px;
        }
        </style>
</head>
<body>
    <div class="header">
        <div style="display: flex; align-items: center; gap: 15px;">
            <h1>BTC Footprint + OB Live v9</h1>
            <div class="ob-legend">
                <div class="ob-legend-item"><div class="ob-color-box ob-bid-color"></div><span>Bids</span></div>
                <div class="ob-legend-item"><div class="ob-color-box ob-ask-color"></div><span>Asks</span></div>
            </div>
            <div class="ob-summary"><span>Orders: <span class="ob-count" id="obTotal">-</span></span> <span style="margin-left: 15px; padding-left: 15px; border-left: 1px solid #333;">OB Δ: <span id="obDeltaHeader" class="ob-count" style="font-weight: bold;">-</span></span></div>
        </div>
        <div class="controls">
            <select id="interval" onchange="changeTimeframe()">
                <option value="1m" selected>1m</option>
                <option value="5m">5m</option>
                <option value="15m">15m</option>
                <option value="30m">30m</option>
                <option value="1h">1h</option>
                <option value="1d">1d</option>
            </select>
            <select id="step" onchange="loadData()">
                <option value="1">1$</option>
                <option value="5">5$</option>
                <option value="10" selected>10$</option>
                <option value="25">25$</option>
                <option value="50">50$</option>
                <option value="100">100$</option>
                <option value="250">250$</option>
            </select>
            <button onclick="loadData()">Aggiorna</button>
            <button id="autoRefreshBtn" onclick="toggleAutoRefresh()">Auto</button>
        </div>
    </div>
    <div class="stats-bar" id="stats-bar">Caricamento...</div>
    <div class="trading-signal" id="trading-signal">Caricamento...</div>
    <div class="navigation">
        <button onclick="scrollBars(-10)"><<<</button>
        <button onclick="scrollBars(-1)"><</button>
        <input type="range" id="rangeSlider" min="0" max="100" value="100" oninput="updateRange(this.value)">
        <span id="rangeLabel">-</span>
        <button onclick="scrollBars(1)">></button>
        <button onclick="scrollBars(10)">>>></button>
        <button onclick="resetView()">Reset</button>
        <div class="zoom-controls">
            <input type="range" id="zoomSlider" class="zoom-slider" min="50" max="150" value="100" oninput="applyZoom(this.value)">
        </div>
    </div>
    <div class="loading" id="loading">Caricamento...</div>
    <div class="chart-container" id="chart-container">In attesa...</div>
    <script>
        let currentData = null, orderBookData = null, viewStart = 0, viewCount = 22, isFirstLoad = true;
        let autoRefreshInterval = null, obRefreshInterval = null;
        let currentInterval = '1m', currentStep = '10';
        const refreshIntervals = {'1m': 15000, '5m': 30000, '15m': 60000, '30m': 60000, '1h': 60000, '1d': 300000};
        
        function changeTimeframe() {
            currentInterval = document.getElementById('interval').value;
            isFirstLoad = true;  // Reset per nuovo timeframe
            if (autoRefreshInterval) {
                clearInterval(autoRefreshInterval);
                autoRefreshInterval = setInterval(() => loadDataLastOnly(), refreshIntervals[currentInterval] || 30000);
            }
            loadData();
        }
        
        function toggleAutoRefresh() {
            const btn = document.getElementById('autoRefreshBtn');
            if (autoRefreshInterval) {
                clearInterval(autoRefreshInterval);
                autoRefreshInterval = null;
                btn.style.background = '#2a2a2a';
            } else {
                const interval = refreshIntervals[currentInterval] || 30000;
                autoRefreshInterval = setInterval(() => loadDataLastOnly(), interval);
                btn.style.background = '#26a69a';
            }
        }
        
        function loadData() {
            document.getElementById('loading').classList.add('active');
            const interval = document.getElementById('interval').value;
            const step = document.getElementById('step').value;
            currentInterval = interval;
            currentStep = step;
            
            fetch('/api/data?interval=' + interval + '&step=' + step)
                .then(r => r.json())
                .then(data => {
                    if (!data || !data.bars || data.bars.length === 0) {
                        document.getElementById('chart-container').innerHTML = '<div style="color: #f44336; text-align: center; padding: 20px;">Errore caricamento</div>';
                        document.getElementById('loading').classList.remove('active');
                        return;
                    }
                    currentData = data;
                    renderStatsBar(data.stats);
                    return fetch('/api/orderbook');
                })
                .then(r => r.json())
                .then(obData => {
                    orderBookData = obData || {bids: [], asks: []};
                    updateObDisplay();
                    startObRefresh();
                    resetView();
                    document.getElementById('loading').classList.remove('active');
                })
                .catch(e => {
                    console.error(e);
                    document.getElementById('loading').classList.remove('active');
                });
        }
        
       function loadDataLastOnly() {
            const interval = document.getElementById('interval').value;
            const step = document.getElementById('step').value;

            Promise.all([
                fetch('/api/data?interval=' + interval + '&step=' + step + '&update_last=true').then(r => r.json()),
                fetch('/api/orderbook').then(r => r.json())
            ])
            .then(([data, obData]) => {
                if (data && data.bars && data.bars.length > 0) {
                    const newLastBar = data.bars[data.bars.length - 1];

                    if (currentData && currentData.bars && currentData.bars.length > 0) {
                        const currentLastBar = currentData.bars[currentData.bars.length - 1];

                        if (currentLastBar.time === newLastBar.time) {
                            // Stessa candela: aggiorna
                            currentData.bars[currentData.bars.length - 1] = newLastBar;
                        } else {
                            // Nuova candela: aggiungi
                            currentData.bars.push(newLastBar);
                        }
                        currentData.stats = data.stats;
                    } else {
                        currentData = { bars: data.bars, stats: data.stats };
                    }

                    orderBookData = obData || {bids: [], asks: []};
                    updateObDisplay();
                    renderStatsBar(data.stats);

                    viewStart = Math.max(0, currentData.bars.length - viewCount);
                    const slider = document.getElementById('rangeSlider');
                    if (slider) {
                        slider.max = Math.max(0, currentData.bars.length - viewCount);
                        slider.value = viewStart;
                    }

                    renderChart();
                }
            })
            .catch(e => {
                console.error("Errore in loadDataLastOnly:", e);
            });
         }


        
        function startObRefresh() {
            if (obRefreshInterval) clearInterval(obRefreshInterval);
            obRefreshInterval = setInterval(() => {
                fetch('/api/orderbook')
                    .then(r => r.json())
                    .then(obData => {
                        if (obData && obData.bids) {
                            orderBookData = obData;
                            updateObDisplay();
                            renderChart();
                            
                        }
                    })
                    .catch(e => console.error(e));
            }, 5000);
        }
        
        function updateObDisplay() {
            if (!orderBookData) return;
            const bidCount = (orderBookData.bids || []).length;
            const askCount = (orderBookData.asks || []).length;
            document.getElementById('obTotal').textContent = (bidCount + askCount);

            let bidQty = 0, askQty = 0;
            (orderBookData.bids || []).forEach(p => { bidQty += parseFloat(p[1] || 0); });
            (orderBookData.asks || []).forEach(p => { askQty += parseFloat(p[1] || 0); });
            const obDelta = bidQty - askQty;
            const obDeltaEl = document.getElementById('obDeltaHeader');
            if (obDeltaEl) {
                obDeltaEl.textContent = (obDelta >= 0 ? '+' : '') + obDelta.toFixed(2);
                obDeltaEl.style.color = obDelta >= 0 ? '#00ff00' : '#ff4444';
            }
        }

        function calculateTradingSignal() {
            if (!currentData || !currentData.stats || !orderBookData) {
                return { signal: 'neutral', strength: 0, obDelta: 0, footprintDelta: 0, volumeRatio: 0 };
            }

            const stats = currentData.stats;

            // Calcola OB Delta
            let bidQty = 0, askQty = 0;
            (orderBookData.bids || []).forEach(p => { bidQty += parseFloat(p[1] || 0); });
            (orderBookData.asks || []).forEach(p => { askQty += parseFloat(p[1] || 0); });
            const obDelta = bidQty - askQty;

            // Delta Footprint
            const footprintDelta = stats.delta || 0;

            // Volume check
            const avgVolume = stats.volume / Math.max(1, currentData.bars.length);
            const currentBar = currentData.bars[currentData.bars.length - 1];
            const currentVolume = currentBar ? currentBar.volume : 0;
            const volumeRatio = avgVolume > 0 ? currentVolume / avgVolume : 1;

            // Soglie
            const totalQty = Math.abs(bidQty + askQty);
            const OB_DELTA_THRESHOLD = totalQty > 0 ? totalQty * 0.05 : 1;
            const VOLUME_THRESHOLD = 1.2;

            let signal = 'neutral';
            let strength = 0;

            // Segnale BUY
            if (obDelta > OB_DELTA_THRESHOLD && footprintDelta > 0 && volumeRatio > VOLUME_THRESHOLD) {
                signal = 'buy';
                strength = Math.min(100, (Math.abs(obDelta) / OB_DELTA_THRESHOLD) * 50 + volumeRatio * 25);
            }
            // Segnale SELL
            else if (obDelta < -OB_DELTA_THRESHOLD && footprintDelta < 0 && volumeRatio > VOLUME_THRESHOLD) {
                signal = 'sell';
                strength = Math.min(100, (Math.abs(obDelta) / OB_DELTA_THRESHOLD) * 50 + volumeRatio * 25);
            }
            // Segnali moderati
            else if (obDelta > OB_DELTA_THRESHOLD && footprintDelta > 0) {
                signal = 'buy';
                strength = Math.min(70, (Math.abs(obDelta) / OB_DELTA_THRESHOLD) * 35);
            }
            else if (obDelta < -OB_DELTA_THRESHOLD && footprintDelta < 0) {
                signal = 'sell';
                strength = Math.min(70, (Math.abs(obDelta) / OB_DELTA_THRESHOLD) * 35);
            }

            return { 
                signal: signal, 
                strength: Math.round(strength),
                obDelta: obDelta,
                footprintDelta: footprintDelta,
                volumeRatio: volumeRatio.toFixed(2)
            };
        }

        function renderTradingSignal() {
            const signalData = calculateTradingSignal();
            const signalDiv = document.getElementById('trading-signal');

            if (!signalDiv) return;

            let arrow = '', color = '', text = '';

            if (signalData.signal === 'buy') {
                arrow = '▲'; color = '#26a69a'; text = 'BUY';
            } else if (signalData.signal === 'sell') {
                arrow = '▼'; color = '#ef5350'; text = 'SELL';
            } else {
                arrow = '●'; color = '#888'; text = 'NEUTRAL';
            }

            const strengthBar = signalData.strength > 0 ? 
                '<div style="background: rgba(255,255,255,0.1); height: 4px; margin-top: 5px; border-radius: 2px;"><div style="background: ' + color + '; height: 100%; width: ' + signalData.strength + '%; border-radius: 2px;"></div></div>' : '';

            signalDiv.innerHTML = `
                <div style="text-align: center; padding: 10px; background: rgba(0,0,0,0.3); border-radius: 5px; border: 2px solid ${color};">
                    <div style="font-size: 32px; color: ${color}; font-weight: bold;">${arrow}</div>
                    <div style="font-size: 14px; color: ${color}; font-weight: bold; margin-top: 5px;">${text}</div>
                    <div style="font-size: 10px; color: #888; margin-top: 5px;">Strength: ${signalData.strength}%</div>
                    ${strengthBar}
                    <div style="font-size: 9px; color: #666; margin-top: 8px; line-height: 1.4;">
                        OB Δ: ${signalData.obDelta.toFixed(2)}<br>
                        FP Δ: ${signalData.footprintDelta.toFixed(2)}<br>
                        Vol: ${signalData.volumeRatio}x
                    </div>
                </div>
            `;
        }
        
        function renderStatsBar(stats) {
            if (!stats) return;
            const deltaClass = stats.delta >= 0 ? 'positive' : 'negative';
            const deltaSign = stats.delta >= 0 ? '+' : '';
            
            let html = '<div class="stat-item"><span class="stat-label">Prezzo:</span><span class="stat-value">$' + (stats.price || 0).toLocaleString() + '</span></div>';
            html += '<div class="stat-item"><span class="stat-label">Vol:</span><span class="stat-value">' + (stats.volume || 0).toFixed(2) + '</span></div>';
            html += '<div class="stat-item"><span class="stat-label">Delta:</span><span class="stat-value ' + deltaClass + '">' + deltaSign + (stats.delta || 0).toFixed(2) + '</span></div>';
            
            if (orderBookData && (orderBookData.bids || []).length > 0) {
                let bidQty = 0, askQty = 0;
                (orderBookData.bids || []).forEach(p => { bidQty += parseFloat(p[1] || 0); });
                (orderBookData.asks || []).forEach(p => { askQty += parseFloat(p[1] || 0); });
                const obDelta = bidQty - askQty;
                const obClass = obDelta >= 0 ? 'positive' : 'negative';
                html += '<div class="stat-item"><span class="stat-label">OB Delta:</span><span class="stat-value ' + obClass + '">' + (obDelta >= 0 ? '+' : '') + obDelta.toFixed(2) + '</span></div>';
            }
            
            document.getElementById('stats-bar').innerHTML = html;
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
        
        function applyZoom(value) {
            const scale = value / 100;
            viewCount = Math.round(22 * (100 / value));
            viewCount = Math.max(10, Math.min(150, viewCount));
            const style = document.createElement('style');
            style.id = 'zoom-style';
            const old = document.getElementById('zoom-style');
            if (old) old.remove();
            // CRITICO: override width con !important per forzare il cambio
            const baseW = 70;
            const w = Math.round(baseW * scale);
            style.textContent = 
                '.bar-column { width: ' + w + 'px !important; max-width: ' + w + 'px !important; min-width: ' + w + 'px !important; flex: 0 0 ' + w + 'px !important; } ' +
                '.price-cell { width: ' + w + 'px !important; max-width: ' + w + 'px !important; flex: 0 0 ' + w + 'px !important; }';
            document.head.appendChild(style);
            if (currentData) {
                viewCount = Math.round(22 * (100 / value));
                viewStart = Math.max(0, currentData.bars.length - viewCount);
                const s = document.getElementById('rangeSlider');
                if (s) { s.max = Math.max(0, currentData.bars.length - viewCount); s.value = viewStart; }
                renderChart();
            }
        }
        
        function renderChart() {
            if (!currentData || !currentData.bars) return;
            
            const displayBars = currentData.bars.slice(viewStart, viewStart + viewCount);
            document.getElementById('rangeLabel').textContent = (viewStart + 1) + '-' + (viewStart + displayBars.length);
            
            let allPrices = new Set();
            displayBars.forEach(bar => {
                if (bar.levels) bar.levels.forEach(l => { allPrices.add(l.price); });
            });
            const sortedPrices = Array.from(allPrices).sort((a, b) => b - a);
            
            const obMap = {};
            if (orderBookData && orderBookData.bids) {
                const step = parseFloat(currentStep);
                (orderBookData.bids || []).forEach(pair => {
                    const p = Math.round(parseFloat(pair[0] || 0) / step) * step;
                    if (!obMap[p]) obMap[p] = {bid: 0, ask: 0};
                    obMap[p].bid += parseFloat(pair[1] || 0);
                });
                (orderBookData.asks || []).forEach(pair => {
                    const p = Math.round(parseFloat(pair[0] || 0) / step) * step;
                    if (!obMap[p]) obMap[p] = {bid: 0, ask: 0};
                    obMap[p].ask += parseFloat(pair[1] || 0);
                });
            }
            
            let maxObVol = 0;
            Object.keys(obMap).forEach(k => { maxObVol = Math.max(maxObVol, obMap[k].bid, obMap[k].ask); });
            
            let html = '<table class="footprint-table" style="width: 100%; border-collapse: collapse;"><tr>';
            displayBars.forEach(bar => {
                html += '<td class="bar-column time-header"><div class="time-text">' + bar.time + '</div><div class="ohlc-text">O:' + bar.open + ' H:' + bar.high + ' L:' + bar.low + ' C:' + bar.close + '</div></td>';
            });
            html += '</tr>';
            
            sortedPrices.forEach(price => {
                html += '<tr class="price-row">';
                displayBars.forEach((bar, idx) => {
                    const level = (bar.levels || []).find(l => l.price === price);
                    const isLast = (idx === displayBars.length - 1);
                    
                    let cellClass = 'bar-column price-cell';
                    if (level && level.in_body) cellClass += bar.bullish ? ' in-body bullish' : ' in-body bearish';
                    if (bar.open_rounded === price) cellClass += bar.bullish ? ' open-level' : ' open-level bearish';
                    if (bar.close_rounded === price) cellClass += bar.bullish ? ' close-level' : ' close-level bearish';
                    
                    let content = '<div class="price-label">' + price + '</div>';
                    if (level && (level.bid > 0 || level.ask > 0)) {
                        const bidSig = level.significant && level.bid > 0 ? ' significant' : '';
                        const askSig = level.significant && level.ask > 0 ? ' significant' : '';
                        content = '<div class="price-cell-content">' + 
                                  (level.bid > 0 ? '<div class="bid-value' + bidSig + '">' + level.bid.toFixed(1) + '</div>' : '') +
                                  (level.ask > 0 ? '<div class="ask-value' + askSig + '">' + level.ask.toFixed(1) + '</div>' : '') +
                                  '</div>' + content;
                    }
                    
                    let obOverlay = '';
                    if (isLast && obMap[price]) {
                        const bidW = maxObVol > 0 ? (obMap[price].bid / maxObVol) * 40 : 0;
                        const askW = maxObVol > 0 ? (obMap[price].ask / maxObVol) * 40 : 0;
                        if (bidW > 0) obOverlay += '<div class="ob-bid-bar" style="width: ' + bidW + '%"></div>';
                        if (askW > 0) obOverlay += '<div class="ob-ask-bar" style="width: ' + askW + '%; left: ' + bidW + '%;"></div>';
                    }
                    
                    html += '<td class="' + cellClass + '"><div class="orderbook-overlay">' + obOverlay + '</div>' + content + '</td>';
                });
                html += '</tr>';
            });
            
            html += '<tr>';
            displayBars.forEach(bar => {
                const deltaClass = bar.delta >= 0 ? 'positive' : 'negative';
                html += '<td class="bar-column delta-footer"><div class="delta-value ' + deltaClass + '">' + (bar.delta >= 0 ? '+' : '') + bar.delta.toFixed(1) + '</div></td>';
            });
            html += '</tr></table>';
            
            document.getElementById('chart-container').innerHTML = html;
            renderTradingSignal();
        }
        
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
    update_last_only = request.args.get('update_last', 'false') == 'true'
    cache_key = f"{interval}_{step}"
    
    with CACHE['lock']:
        if cache_key in CACHE['data'] and not update_last_only:
            entry = CACHE['data'][cache_key]
            return jsonify(entry['data'])
        
        data = process_data(interval, step, update_last_only)
        
        if not update_last_only:
            CACHE['data'][cache_key] = {'data': data, 'timestamp': time.time()}
    
    return jsonify(data)

@app.route('/api/orderbook')
def get_orderbook():
    with CACHE['lock']:
        if 'orderbook' in CACHE and time.time() - CACHE['orderbook'].get('timestamp', 0) < 3:
            return jsonify(CACHE['orderbook']['data'])
        
        ob_data = fetch_orderbook()
        CACHE['orderbook'] = {'data': ob_data, 'timestamp': time.time()}
    
    return jsonify(ob_data)

if __name__ == '__main__':
    print("=" * 70)
    print("BTC FOOTPRINT v9 - LAYOUT STESSO LATO")
    print("=" * 70)
    print("✅ Bid e Ask affiancati da sinistra")
    print("✅ Layout orizzontale comprensibile")
    print("✅ Cache infinita + Auto-refresh")
    print("=" * 70)
    print("http://localhost:5000")
    print("=" * 70)
    app.run(debug=True, host='0.0.0.0', port=5000, threaded=True)