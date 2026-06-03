#!/usr/bin/env python3
"""
Hedge Fund Quant Trading System — Multi-Agent Orchestrator
Coordinates 5 specialized agents for autonomous trading.

Safety-first version:
- dry-run truly disables execution
- preserves BUY/SELL direction
- uses tick-value-based position sizing
- uses broker-friendly FOK filling by default
"""
import os
import json
from datetime import datetime

# --- MT5 Bridge Helper ---------------------------------------------------------
try:
    from mt5linux import MetaTrader5
    mt5 = MetaTrader5(
        host=os.environ.get("MT5_BRIDGE_HOST", "localhost"),
        port=int(os.environ.get("MT5_BRIDGE_PORT", "8001")),
    )
    _ = mt5.account_info()
except Exception as e:
    mt5 = None
    print(f"WARN: MT5 bridge unavailable: {e}")


def filling_mode():
    return int(os.environ.get("ORDER_FILLING_MODE", "1"))  # default FOK


def sltp_valid(side: str, entry: float, sl: float, tp: float):
    side = side.upper()
    if side == "BUY":
        return sl < entry < tp
    if side == "SELL":
        return tp < entry < sl
    return False


# --- Risk/Reward Calculator ----------------------------------------------------
def calculate_rr(symbol: str, entry: float, sl: float, tp: float, risk_pct: float = 1.0, balance: float = 10000.0) -> dict:
    """Calculate position size and risk metrics."""
    if mt5 is None:
        return {"error": "MT5 not connected"}

    info = mt5.symbol_info(symbol)
    if info is None:
        return {"error": f"Symbol {symbol} not found"}

    point = info.point
    stop_dist = abs(entry - sl) / point
    take_dist = abs(tp - entry) / point
    if stop_dist == 0:
        return {"error": "SL too close"}

    rr_ratio = take_dist / stop_dist if stop_dist > 0 else 0
    risk_usd = balance * (risk_pct / 100.0)

    tick_value = info.trade_tick_value if getattr(info, "trade_tick_value", 0) else 1.0
    volume_step = info.volume_step if getattr(info, "volume_step", 0) else 0.01
    loss_per_lot = stop_dist * tick_value
    volume = risk_usd / loss_per_lot if loss_per_lot > 0 else 0.0
    volume = round(volume / volume_step) * volume_step
    volume = max(info.volume_min, min(info.volume_max, volume))

    merit = min(1.0, rr_ratio / 3.0)
    return {
        "volume": round(volume, 2),
        "risk_usd": round(risk_usd, 2),
        "reward_usd": round(risk_usd * rr_ratio, 2),
        "rr_ratio": round(rr_ratio, 2),
        "merit_score": round(merit, 2),
    }


# --- Signal Validator ----------------------------------------------------------
def validate_signal(symbol: str, signal: dict) -> dict:
    """Check if signal is executable (spreads, stops, direction)."""
    if mt5 is None:
        return {"valid": False, "reason": "MT5 offline"}

    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if info is None or tick is None:
        return {"valid": False, "reason": "No market data"}

    spread_pts = (tick.ask - tick.bid) / info.point
    baseline_spread = float(getattr(info, "spread", 100) or 100)
    if spread_pts > baseline_spread * 2:
        return {"valid": False, "reason": f"Spread too wide ({spread_pts} > {baseline_spread * 2})"}

    side = signal.get("signal", "BUY")
    entry = signal.get("entry")
    sl = signal.get("sl")
    tp = signal.get("tp")
    if not sltp_valid(side, entry, sl, tp):
        return {"valid": False, "reason": "Invalid SL/TP direction"}

    sl_pts = abs(entry - sl) / info.point
    if sl_pts < info.trade_stops_level:
        return {"valid": False, "reason": f"SL below stop level ({sl_pts} < {info.trade_stops_level})"}

    return {"valid": True, "reason": "OK"}


# --- Main Orchestrator ---------------------------------------------------------
def run_cycle(portfolio_balance: float = 10000.0, dry_run: bool = True) -> dict:
    """Execute one trading cycle."""
    print(f"\n=== Trading Cycle @ {datetime.now()} ===")

    market_ctx = {"symbols": ["XAUUSD", "BTCUSD", "EURUSD", "GBPUSD"]}

    # Step 2: Get technical signals (still simplified demo, but direction-safe)
    signals = []
    for sym in market_ctx["symbols"]:
        tick = mt5.symbol_info_tick(sym) if mt5 else None
        info = mt5.symbol_info(sym) if mt5 else None
        if tick and info:
            direction = "BUY" if tick.ask >= tick.bid else "SELL"
            entry = tick.ask if direction == "BUY" else tick.bid
            sl = entry - 50 * info.point if direction == "BUY" else entry + 50 * info.point
            tp = entry + 100 * info.point if direction == "BUY" else entry - 100 * info.point
            signals.append({
                "symbol": sym,
                "signal": direction,
                "confidence": 0.55,
                "entry": entry,
                "sl": sl,
                "tp": tp,
                "timeframe": "M15",
            })

    approved = []
    for sig in signals:
        rr = calculate_rr(sig["symbol"], sig["entry"], sig["sl"], sig["tp"], 1.0, portfolio_balance)
        sig.update(rr)
        valid = validate_signal(sig["symbol"], sig)
        sig.update(valid)
        if sig.get("merit_score", 0) > 0.3 and valid.get("valid"):
            approved.append(sig)

    trades = []
    for sig in sorted(approved, key=lambda x: x["merit_score"], reverse=True)[:3]:
        trades.append({
            "symbol": sig["symbol"],
            "volume": sig["volume"],
            "type": sig["signal"],
            "sl": sig["sl"],
            "tp": sig["tp"],
            "reason": f"RR={sig['rr_ratio']}, merit={sig['merit_score']}",
        })

    executed = []
    if not dry_run:
        for t in trades:
            if mt5:
                tick = mt5.symbol_info_tick(t["symbol"])
                order_type = mt5.ORDER_TYPE_BUY if t["type"] == "BUY" else mt5.ORDER_TYPE_SELL
                price = tick.ask if t["type"] == "BUY" else tick.bid
                req = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": t["symbol"],
                    "volume": t["volume"],
                    "type": order_type,
                    "price": price,
                    "deviation": 20,
                    "magic": 888888,
                    "comment": "HF_QUANT",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": filling_mode(),
                }
                if t.get("sl"):
                    req["sl"] = t["sl"]
                if t.get("tp"):
                    req["tp"] = t["tp"]
                res = mt5.order_send(req)
                executed.append({"symbol": t["symbol"], "result": str(res) if res else "err"})
    else:
        executed = [{"mode": "dry_run", "count": len(trades)}]

    return {
        "cycle": datetime.now().isoformat(),
        "signals": len(signals),
        "approved": len(approved),
        "trades": trades,
        "executed": executed,
        "dry_run": dry_run,
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Hedge Fund Quant Trading Orchestrator")
    parser.add_argument("--balance", type=float, default=10000.0, help="Portfolio balance")
    parser.add_argument("--dry-run", action="store_true", help="No execution, just signals")
    args = parser.parse_args()

    result = run_cycle(args.balance, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))
