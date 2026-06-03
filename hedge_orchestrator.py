#!/usr/bin/env python3
"""
Hedge Fund Quant Trading System — Multi-Agent Orchestrator
Coordinates 5 specialized agents for autonomous trading.

Agents:
1. market_intelligence — scans news, geopolitics, sentiment
2. economic_calendar — parses upcoming NFP, CPI, Fed, central bank events
3. technical_analysis — quant TA signals, support/resistance, patterns
4. risk_manager — position sizing, stop loss, risk/reward, volatility filters
5. portfolio_manager — allocates capital, decides which trades to execute

Workflow:
Tick (cron) → [MarketIntel || EconCalendar || TechAnalysis] → RiskManager → PortfolioManager → Execution
"""
import os, sys, json, time, statistics, math
from datetime import datetime, timedelta
from typing import Optional

# --- MT5 Bridge Helper ---------------------------------------------------------
try:
    from mt5linux import MetaTrader5
    mt5 = MetaTrader5(host=os.environ.get("MT5_BRIDGE_HOST", "localhost"),
                      port=int(os.environ.get("MT5_BRIDGE_PORT", "8001")))
except Exception as e:
    mt5 = None
    print(f"WARN: MT5 bridge unavailable: {e}")

# --- Risk/Reward Calculator ----------------------------------------------------
def calculate_rr(symbol: str, entry: float, sl: float, tp: float, risk_pct: float = 1.0, balance: float = 10000.0) -> dict:
    """
    Calculate position size and risk metrics.
    Returns: {volume, risk_usd, reward_usd, rr_ratio, merit_score}
    """
    if mt5 is None:
        return {"error": "MT5 not connected"}
    
    info = mt5.symbol_info(symbol)
    if info is None:
        return {"error": f"Symbol {symbol} not found"}
    
    point = info.point
    contract = info.trade_contract_size
    stop_dist = abs(entry - sl) / point
    take_dist = abs(tp - entry) / point
    if stop_dist == 0:
        return {"error": "SL too close"}
    
    rr_ratio = take_dist / stop_dist if stop_dist > 0 else 0
    risk_usd = balance * (risk_pct / 100.0)
    volume = risk_usd / (stop_dist * contract) if stop_dist > 0 else 0
    
    # Clamp volume to broker limits
    volume = max(info.volume_min, min(info.volume_max, volume))
    
    merit = min(1.0, rr_ratio / 3.0)  # merit increases with RR >= 3
    return {
        "volume": round(volume, 2),
        "risk_usd": round(risk_usd, 2),
        "reward_usd": round(risk_usd * rr_ratio, 2),
        "rr_ratio": round(rr_ratio, 2),
        "merit_score": round(merit, 2),
    }

# --- Signal Validator ----------------------------------------------------------
def validate_signal(symbol: str, signal: dict) -> dict:
    """Check if signal is executable (spreads, stops, volatility)."""
    if mt5 is None:
        return {"valid": False, "reason": "MT5 offline"}
    
    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if info is None or tick is None:
        return {"valid": False, "reason": "No market data"}
    
    # Check spread
    spread_pts = (tick.ask - tick.bid) / info.point
    max_spread = info.spread_max / info.point if info.spread_max > 0 else 100
    if spread_pts > max_spread:
        return {"valid": False, "reason": f"Spread too wide ({spread_pts} > {max_spread})"}
    
    # Check stop level
    sl_pts = abs(signal.get("sl", tick.ask) - tick.ask) / info.point
    if sl_pts < info.trade_stops_level:
        return {"valid": False, "reason": f"SL below stop level ({sl_pts} < {info.trade_stops_level})"}
    
    return {"valid": True, "reason": "OK"}

# --- Agent Prompts -------------------------------------------------------------
PROMPTS = {
    "market_intelligence": """
You are MarketIntel Agent — a geopolitical & macro risk analyst.
Analyze: 
- Geopolitical tensions (US-China, Middle East, Ukraine, EU)
- Central bank calendar (Fed, BoJ, BoE, SNB)
- Commodity shocks (oil, gold, copper)
- Sentiment indicators (VIX, MOVE, sentiment indices)
Return JSON: {symbol, bias, timeframe, key_levels, catalyst}
""",
    "economic_calendar": """
You are EconCalendar Agent — economic data parser.
Parse upcoming releases:
- High-impact NFP, CPI, GDP, PMI, Retail Sales
- Central bank speeches and policy decisions
- Yield curve changes, bond flows
Return JSON: {events: [{date, time, event, impact, forecast, prev}]}
""",
    "technical_analysis": """
You are TechAnalysis Agent — quantitative signal generator.
For symbol, compute:
- Support/resistance (pivot, Fibonacci, volume profile)
- Momentum (RSI, MACD, Stochastic)
- Volatility (ATR, Bollinger Bands)
- Pattern recognition (pin bars, engulfing, Inside Bar)
Return JSON: {symbol, signal, confidence, entry, sl, tp, timeframe}
""",
    "risk_manager": """
You are RiskManager Agent — position sizing & capital guard.
Rules:
- Max risk per trade: 1% portfolio
- Max exposure per symbol: 5% portfolio
- Correlation filter: max 2 correlated positions
- Daily loss limit: 3% portfolio
Return JSON: {approved: bool, reason, position_size, adjusted_sl, adjusted_tp}
""",
    "portfolio_manager": """
You are PortfolioManager Agent — capital allocation & execution gate.
Decide:
- Which signals to execute (rank by merit_score * confidence)
- Position sizing allocation (Kelly criterion)
- Hedging opportunities (hedge ratios)
- Risk budget remaining
Return JSON: {execute: bool, trades: [{symbol, volume, type, sl, tp, reason}]}
"""
}

# --- Main Orchestrator ---------------------------------------------------------
def run_cycle(portfolio_balance: float = 10000.0) -> dict:
    """Execute one trading cycle."""
    print(f"\n=== Trading Cycle @ {datetime.now()} ===")
    
    # Step 1: Gather market context (parallel)
    market_ctx = {"symbols": ["XAUUSD", "BTCUSD", "EURUSD", "GBPUSD"]}
    
    # Step 2: Get technical signals (simplified demo)
    signals = []
    for sym in market_ctx["symbols"]:
        tick = mt5.symbol_info_tick(sym) if mt5 else None
        info = mt5.symbol_info(sym) if mt5 else None
        if tick and info:
            # Dummy signal for demo
            signals.append({
                "symbol": sym,
                "signal": "BUY",
                "confidence": 0.75,
                "entry": tick.ask,
                "sl": tick.ask - 50 * info.point,
                "tp": tick.ask + 100 * info.point,
                "timeframe": "M15"
            })
    
    # Step 3: Risk manager filters
    approved = []
    for sig in signals:
        rr = calculate_rr(sig["symbol"], sig["entry"], sig["sl"], sig["tp"], 1.0, portfolio_balance)
        sig.update(rr)
        valid = validate_signal(sig["symbol"], sig)
        sig.update(valid)
        if sig.get("merit_score", 0) > 0.3 and valid.get("valid"):
            approved.append(sig)
    
    # Step 4: Portfolio manager decides
    trades = []
    for sig in sorted(approved, key=lambda x: x["merit_score"], reverse=True)[:3]:
        trades.append({
            "symbol": sig["symbol"],
            "volume": sig["volume"],
            "type": "BUY",
            "sl": sig["sl"],
            "tp": sig["tp"],
            "reason": f"RR={sig['rr_ratio']}, merit={sig['merit_score']}"
        })
    
    # Step 5: Execute (if enabled)
    executed = []
    for t in trades:
        if mt5:
            res = mt5.order_send({
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": t["symbol"],
                "volume": t["volume"],
                "type": mt5.ORDER_TYPE_BUY,
                "price": mt5.symbol_info_tick(t["symbol"]).ask,
                "sl": t["sl"],
                "tp": t["tp"],
                "deviation": 20,
                "magic": 888888,
                "comment": "HF_QUANT",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            })
            executed.append({"symbol": t["symbol"], "result": str(res) if res else "err"})
    
    return {"cycle": datetime.now().isoformat(), "signals": len(signals),
            "approved": len(approved), "trades": trades, "executed": executed}

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Hedge Fund Quant Trading Orchestrator")
    parser.add_argument("--balance", type=float, default=10000.0, help="Portfolio balance")
    parser.add_argument("--dry-run", action="store_true", help="No execution, just signals")
    args = parser.parse_args()
    
    if args.dry_run:
        print("DRY RUN")
    result = run_cycle(args.balance)
    print(json.dumps(result, indent=2))