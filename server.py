#!/usr/bin/env python3
"""MT5 MCP Server — stdio transport for Hermes."""
import os, sys, logging, zoneinfo
from datetime import datetime, timedelta
logging.basicConfig(level=logging.WARNING)
logging.getLogger("mt5linux").setLevel(logging.ERROR)

from mcp.server.fastmcp import FastMCP, Context
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Optional, Union, List, Dict

from mt5linux import MetaTrader5
import requests
import pandas as pd
import numpy as np

_mt5 = None
_mt5_ok = False
_EARNINGS_API_KEY = os.environ.get("EARNINGS_API_KEY", "")

# --- Risk Parameters (Institutional Grade) ---
MAX_RISK_PER_TRADE = 0.01      # 1% per trade
MAX_DAILY_LOSS = 0.03          # 3% daily max
MIN_RR_RATIO = 1.5             # 1.5:1 minimum
MAX_SYMBOL_EXPOSURE = 0.05     # 5% per symbol
MAX_CORRELATION = 0.7           # 70% correlation limit
NEWS_BLACKOUT_MINUTES = 15      # Pre/post high-impact news
KELLY_FRACTION = 0.25          # Kelly multiplier for safety

def get_mt5():
    global _mt5
    global _mt5_ok
    if _mt5 is None:
        host = os.environ.get("MT5_BRIDGE_HOST", "localhost")
        port = int(os.environ.get("MT5_BRIDGE_PORT", "8001"))
        try:
            _mt5 = MetaTrader5(host=host, port=port)
            _mt5_ok = _mt5.account_info() is not None
            if not _mt5_ok:
                logging.warning(f"MT5 bridge at {host}:{port} unreachable — tools return degraded responses")
        except Exception as e:
            logging.warning(f"MT5 bridge connection failed: {e}")
            _mt5 = None
            _mt5_ok = False
    if not _mt5_ok:
        raise ConnectionError(f"MT5 bridge offline (host={host}:{port})")
    return _mt5

def _sltp_valid(symbol, side, entry, sl, tp):
    """Validate SL/TP direction for BUY/SELL. Returns (valid: bool, reason: str)."""
    if side.upper() not in ("BUY", "SELL"):
        return False, f"Invalid side: {side}"
    if sl is not None and sl > 0 and tp is not None and tp > 0:
        if side.upper() == "BUY":
            if not (sl < entry < tp):
                return False, f"BUY requires SL < entry < TP (got sl={sl} entry={entry} tp={tp})"
        else:
            if not (tp < entry < sl):
                return False, f"SELL requires TP < entry < SL (got tp={tp} entry={entry} sl={sl})"
    return True, "OK"

def _filling_mode():
    """Return broker-appropriate filling mode. HF Markets requires FOK."""
    return int(os.environ.get("ORDER_FILLING_MODE", "1"))  # default FOK (1)

@dataclass
class AppCtx:
    ok: str

@asynccontextmanager
async def lifespan(srv):
    get_mt5()
    yield AppCtx(ok="ready")

mcp = FastMCP("metatrader", lifespan=lifespan)

def _csv(df):
    return df.to_csv() if hasattr(df, "to_csv") else str(df)

def _result_dict(r):
    """Convert OrderSendResult to dict."""
    d = r._asdict()
    if "request" in d:
        d["request"] = d["request"]._asdict()
    return d

def _tick_price(sym, side="ask"):
    """Get current ask or bid price."""
    tick = get_mt5().symbol_info_tick(sym)
    if tick is None:
        raise ValueError(f"No tick data for {sym}")
    return tick.ask if side == "ask" else tick.bid

# ──────────────────────────────────────────────────────────────────────────────
# Account
# ──────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def get_account_info(ctx: Context) -> dict:
    """Account info: balance, equity, profit, margin, leverage, currency."""
    a = get_mt5().account_info()
    return a._asdict() if a else {}

# ──────────────────────────────────────────────────────────────────────────────
# Market Data
# ──────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def get_symbol_price(ctx: Context, symbol_name: str) -> dict:
    """Latest bid/ask/tick for a symbol."""
    return get_mt5().market.get_symbol_price(symbol_name=symbol_name)

@mcp.tool()
def get_symbol_info(ctx: Context, symbol_name: str) -> dict:
    """Full symbol specification: digits, spread, lot min/max, stop_level."""
    info = get_mt5().symbol_info(symbol_name)
    return info._asdict() if info else {}

@mcp.tool()
def get_symbols(ctx: Context, group: Optional[str] = None) -> list:
    """List symbols. Filter: group pattern e.g. '*USD*'."""
    return get_mt5().market.get_symbols(group=group)

@mcp.tool()
def get_all_symbols(ctx: Context) -> list:
    """All available symbols."""
    return get_mt5().market.get_symbols()

@mcp.tool()
def get_candles_latest(ctx: Context, symbol_name: str, timeframe: str = "M1", count: int = 100) -> str:
    """Latest N candles. Timeframes: M1,M5,M15,M30,H1,H4,D1,W1,MN1."""
    return _csv(get_mt5().market.get_candles_latest(symbol_name=symbol_name, timeframe=timeframe, count=count))

@mcp.tool()
def get_candles_by_date(ctx: Context, symbol_name: str, timeframe: str, from_date: str, to_date: Optional[str] = None) -> str:
    """Candles by date range. Dates: YYYY-MM-DD or ISO format."""
    return _csv(get_mt5().market.get_candles_by_date(symbol_name=symbol_name, timeframe=timeframe, from_date=from_date, to_date=to_date))

# ──────────────────────────────────────────────────────────────────────────────
# Positions (read)
# ──────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def get_all_positions(ctx: Context) -> str:
    """All open positions as CSV."""
    return _csv(get_mt5().order.get_all_positions())

@mcp.tool()
def get_positions_by_symbol(ctx: Context, symbol: str) -> str:
    """Open positions for a symbol."""
    return _csv(get_mt5().order.get_positions_by_symbol(symbol=symbol))

# ──────────────────────────────────────────────────────────────────────────────
# Pending Orders (read)
# ──────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def get_all_pending_orders(ctx: Context) -> str:
    """All pending orders as CSV."""
    return _csv(get_mt5().order.get_all_pending_orders())

@mcp.tool()
def get_pending_orders_by_symbol(ctx: Context, symbol: str) -> str:
    """Pending orders for a specific symbol."""
    return _csv(get_mt5().order.get_pending_orders_by_symbol(symbol=symbol))

# ──────────────────────────────────────────────────────────────────────────────
# Open / Close Positions
# ──────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def open_position(ctx: Context, symbol: str, volume: float, type: str,
                  sl: Optional[float] = None, tp: Optional[float] = None,
                  deviation: int = 20, magic: int = 0, comment: str = "mcp") -> dict:
    """
    Open a market position. Parameters:
      symbol:  e.g. 'EURUSD'
      volume:  lot size e.g. 0.01
      type:    'BUY' or 'SELL'
      sl:      stop loss price (omit or None for none)
      tp:      take profit price (omit or None for none)
      deviation: max slippage in points
      magic:   EA magic number
      comment: order comment
    """
    mt5 = get_mt5()
    side = type.upper()
    price = _tick_price(symbol, "ask" if side == "BUY" else "bid")
    type_int = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL

    # Validate SL/TP direction
    valid, reason = _sltp_valid(symbol, side, price, sl, tp)
    if not valid:
        return {"error": reason, "retcode": -1}

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": type_int,
        "price": price,
        "deviation": deviation,
        "magic": magic,
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": _filling_mode(),
    }
    # Omit sl/tp keys if None/0 to avoid broker reject
    if sl is not None and sl > 0:
        request["sl"] = sl
    if tp is not None and tp > 0:
        request["tp"] = tp

    result = mt5.order_send(request)
    if result is None:
        return {"error": str(mt5.last_error())}
    d = _result_dict(result)
    return {"retcode": d["retcode"], "deal": d.get("deal"), "order": d.get("order"),
            "volume": d.get("volume"), "price": d.get("price"),
            "message": "OPENED" if d["retcode"] == 10009 else d.get("comment", "")}

# Backward compat alias
place_market_order = open_position
place_market_order.__name__ = "place_market_order"
place_market_order.__doc__ = """Alias for open_position. Market order: symbol, volume, type (BUY/SELL)."""
mcp.tool()(place_market_order)

@mcp.tool()
def close_position(ctx: Context, id: Union[int, str], deviation: int = 20) -> dict:
    """Close an open position by ticket ID."""
    mt5 = get_mt5()
    id = int(id)
    positions = mt5.positions_get()
    if not positions:
        return {"error": "No open positions found"}
    pos = next((p for p in positions if p.ticket == id), None)
    if pos is None:
        return {"error": f"Position {id} not found"}
    # Opposite type for close
    close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
    price = _tick_price(pos.symbol, "bid" if pos.type == mt5.ORDER_TYPE_BUY else "ask")
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": pos.symbol,
        "volume": pos.volume,
        "type": close_type,
        "position": id,
        "price": price,
        "deviation": deviation,
        "magic": pos.magic,
        "comment": "mcp close",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": _filling_mode(),
    }
    result = mt5.order_send(request)
    if result is None:
        return {"error": str(mt5.last_error())}
    d = _result_dict(result)
    return {"retcode": d["retcode"], "deal": d.get("deal"),
            "volume": d.get("volume"), "price": d.get("price"),
            "message": "CLOSED" if d["retcode"] == 10009 else d.get("comment", "")}

@mcp.tool()
def close_all_positions(ctx: Context, deviation: int = 20) -> list:
    """Close ALL open positions."""
    mt5 = get_mt5()
    positions = mt5.positions_get()
    if not positions:
        return [{"message": "No open positions"}]
    results = []
    for pos in positions:
        close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        price = _tick_price(pos.symbol, "bid" if pos.type == mt5.ORDER_TYPE_BUY else "ask")
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": pos.symbol,
            "volume": pos.volume,
            "type": close_type,
            "position": pos.ticket,
            "price": price,
            "deviation": deviation,
            "magic": pos.magic,
            "comment": "mcp close all",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": _filling_mode(),
        }
        result = mt5.order_send(request)
        d = _result_dict(result) if result else {"error": str(mt5.last_error())}
        results.append({"ticket": pos.ticket, "symbol": pos.symbol, "retcode": d.get("retcode")})
    return results

# ──────────────────────────────────────────────────────────────────────────────
# Modify Position (SL / TP)
# ──────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def modify_position(ctx: Context, id: Union[int, str],
                    sl: Optional[float] = None, tp: Optional[float] = None) -> dict:
    """
    Modify SL/TP of an open position. Pass ticket id and at least sl or tp.
    Set to 0.0 to remove SL/TP.
    """
    mt5 = get_mt5()
    id = int(id)
    positions = mt5.positions_get()
    if not positions:
        return {"error": "No open positions found"}
    pos = next((p for p in positions if p.ticket == id), None)
    if pos is None:
        return {"error": f"Position {id} not found"}
    new_sl = sl if sl is not None else pos.sl
    new_tp = tp if tp is not None else pos.tp

    # Direction-aware validation for modify
    side = "BUY" if pos.type == 0 else "SELL"
    valid, reason = _sltp_valid(pos.symbol, side, pos.price_open, new_sl, new_tp)
    if not valid:
        return {"error": reason, "retcode": -1}

    request = {
        "action": mt5.TRADE_ACTION_SLTP,
        "position": id,
        "symbol": pos.symbol,
        "sl": new_sl,
        "tp": new_tp,
        "magic": pos.magic,
    }
    result = mt5.order_send(request)
    if result is None:
        return {"error": str(mt5.last_error())}
    d = _result_dict(result)
    return {"retcode": d["retcode"],
            "sl": new_sl, "tp": new_tp,
            "message": "MODIFIED" if d["retcode"] == 10009 else d.get("comment", "")}

# ──────────────────────────────────────────────────────────────────────────────
# Pending Orders
# ──────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def place_pending_order(ctx: Context, symbol: str, volume: float, type: str,
                        price: float, sl: Optional[float] = None, tp: Optional[float] = None,
                        deviation: int = 20, magic: int = 0,
                        comment: str = "mcp") -> dict:
    """
    Place a pending order. Parameters:
      symbol:  e.g. 'EURUSD'
      volume:  lot size
      type:    'BUY_LIMIT', 'SELL_LIMIT', 'BUY_STOP', 'SELL_STOP'
      price:   trigger price
      sl:      stop loss (omit or None for none)
      tp:      take profit (omit or None for none)
    """
    mt5 = get_mt5()
    order_type = type.upper()
    type_map = {
        "BUY_LIMIT": mt5.ORDER_TYPE_BUY_LIMIT,
        "SELL_LIMIT": mt5.ORDER_TYPE_SELL_LIMIT,
        "BUY_STOP": mt5.ORDER_TYPE_BUY_STOP,
        "SELL_STOP": mt5.ORDER_TYPE_SELL_STOP,
    }
    type_int = type_map.get(order_type)
    if type_int is None:
        return {"error": f"Invalid type: {type}. Use BUY_LIMIT/SELL_LIMIT/BUY_STOP/SELL_STOP"}

    # Validate pending trigger price relative to market
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return {"error": f"No tick data for {symbol}"}
    if order_type == "BUY_LIMIT" and price >= tick.ask:
        return {"error": f"BUY_LIMIT price must be below ask ({tick.ask})"}
    if order_type == "SELL_LIMIT" and price <= tick.bid:
        return {"error": f"SELL_LIMIT price must be above bid ({tick.bid})"}
    if order_type == "BUY_STOP" and price <= tick.ask:
        return {"error": f"BUY_STOP price must be above ask ({tick.ask})"}
    if order_type == "SELL_STOP" and price >= tick.bid:
        return {"error": f"SELL_STOP price must be below bid ({tick.bid})"}

    # Validate SL/TP direction (map pending type to side)
    side = "BUY" if order_type.startswith("BUY") else "SELL"
    valid, reason = _sltp_valid(symbol, side, price, sl, tp)
    if not valid:
        return {"error": reason, "retcode": -1}

    request = {
        "action": mt5.TRADE_ACTION_PENDING,
        "symbol": symbol,
        "volume": volume,
        "type": type_int,
        "price": price,
        "deviation": deviation,
        "magic": magic,
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": _filling_mode(),
    }
    if sl is not None and sl > 0:
        request["sl"] = sl
    if tp is not None and tp > 0:
        request["tp"] = tp

    result = mt5.order_send(request)
    if result is None:
        return {"error": str(mt5.last_error())}
    d = _result_dict(result)
    return {"retcode": d["retcode"], "order": d.get("order"), "price": d.get("price"),
            "message": "PENDING PLACED" if d["retcode"] == 10009 else d.get("comment", "")}

@mcp.tool()
def cancel_pending_order(ctx: Context, id: Union[int, str]) -> dict:
    """Cancel a pending order by ticket ID."""
    mt5 = get_mt5()
    id = int(id)
    request = {
        "action": mt5.TRADE_ACTION_REMOVE,
        "order": id,
    }
    result = mt5.order_send(request)
    if result is None:
        return {"error": str(mt5.last_error())}
    d = _result_dict(result)
    return {"retcode": d["retcode"],
            "message": "CANCELLED" if d["retcode"] == 10009 else d.get("comment", "")}

@mcp.tool()
def cancel_all_pending_orders(ctx: Context) -> list:
    """Cancel all pending orders."""
    mt5 = get_mt5()
    orders = mt5.orders_get()
    if not orders:
        return [{"message": "No pending orders"}]
    results = []
    for o in orders:
        request = {"action": mt5.TRADE_ACTION_REMOVE, "order": o.ticket}
        result = mt5.order_send(request)
        d = _result_dict(result) if result else {"error": str(mt5.last_error())}
        results.append({"ticket": o.ticket, "symbol": o.symbol, "retcode": d.get("retcode")})
    return results


# ──────────────────────────────────────────────────────────────────────────────
# Economic Calendar (via EarningsAPI)
# ──────────────────────────────────────────────────────────────────────────────

def _fetch_calendar(date: str, usmajor: bool = False) -> list:
    url = f"https://api.earningsapi.com/v1/calendar/economic?date={date}&usmajor={str(usmajor).lower()}&apikey={_EARNINGS_API_KEY}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return [{"error": f"Failed to fetch economic calendar: {str(e)}"}]

@mcp.tool()
def get_economic_calendar_today(ctx: Context, usmajor: bool = False) -> list:
    """
    Get today's economic calendar events (NY time).
    Parameters:
      usmajor: if true, returns U.S. major indicators only (default: false)
    """
    return _fetch_calendar(datetime.now().strftime('%Y-%m-%d'), usmajor)

@mcp.tool()
def get_economic_calendar_yesterday(ctx: Context, usmajor: bool = False) -> list:
    """
    Get yesterday's economic calendar events (NY time).
    Parameters:
      usmajor: if true, returns U.S. major indicators only (default: false)
    """
    return _fetch_calendar((datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d'), usmajor)

@mcp.tool()
def get_economic_calendar_date(ctx: Context, date: str, usmajor: bool = False) -> list:
    """
    Get economic calendar events for a specific date (NY time).
    Parameters:
      date: YYYY-MM-DD format, or 'today', 'yesterday', 'tomorrow'
      usmajor: if true, returns U.S. major indicators only (default: false)
    """
    return _fetch_calendar(date, usmajor)

# ──────────────────────────────────────────────────────────────────────────────
# Quant Trading Tools
# ──────────────────────────────────────────────────────────────────────────────

def _get_candles_df(symbol: str, tf: str = "M15", count: int = 200) -> pd.DataFrame:
    """Fetch candles as DataFrame for indicator calculation."""
    try:
        raw = get_mt5().market.get_candles_latest(symbol_name=symbol, timeframe=tf, count=count)
        if raw is None or raw.empty:
            return pd.DataFrame()
        df = raw.copy()
        # Flatten MultiIndex columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df
    except Exception:
        return pd.DataFrame()

@mcp.tool()
def calculate_kelly_position(ctx: Context, symbol: str, entry: float, sl: float, tp: float,
                             balance: float = 10000.0, risk_pct: Optional[float] = None) -> dict:
    """
    Calculate position size using Kelly criterion.
    Variables:
      symbol:  e.g. 'EURUSD'
      entry:   planned entry price
      sl:      stop loss price
      tp:      take profit price
      balance: current account balance (default 10000)
      risk_pct: optional % of balance to risk (default: use MAX_RISK_PER_TRADE=1%)
    Returns: {volume, risk_usd, reward_usd, rr_ratio, kelly_pct, merit_score, stop_pts, take_pts, validation}
    """
    mt5 = get_mt5()
    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if not info or not tick:
        return {"error": f"No market data for {symbol}"}

    point = info.point
    tick_side = tick.ask if entry >= tick.ask else tick.bid

    stop_pts = abs(entry - sl) / point
    take_pts = abs(tp - entry) / point

    if stop_pts < info.trade_stops_level:
        return {"error": f"SL {stop_pts:.0f}pts below stop level {info.trade_stops_level}"}
    if stop_pts == 0:
        return {"error": "SL == entry price"}

    rr = round(take_pts / stop_pts, 2)
    if rr < MIN_RR_RATIO:
        return {"error": f"RR {rr}:1 < minimum {MIN_RR_RATIO}:1"}

    risk_pct_val = risk_pct if risk_pct is not None else MAX_RISK_PER_TRADE
    risk_usd = balance * risk_pct_val

    # Use tick_value for accurate position sizing
    tick_size = info.trade_tick_size if info.trade_tick_size and info.trade_tick_size > 0 else point
    tick_value = info.trade_tick_value if info.trade_tick_value and info.trade_tick_value > 0 else 1.0
    loss_per_lot = stop_pts * tick_value
    volume = risk_usd / loss_per_lot if loss_per_lot > 0 else 0

    # Quantize to volume_step
    volume_step = info.volume_step if info.volume_step and info.volume_step > 0 else 0.01
    volume = round(volume / volume_step) * volume_step

    # Kelly cap
    p = 0.55
    q = 1 - p
    kelly_raw = (p * rr - q) / rr if rr > 0 else 0
    kelly_frac = max(0, kelly_raw * KELLY_FRACTION)
    volume = min(volume, info.volume_max * kelly_frac) if kelly_frac > 0 else volume

    volume = round(max(info.volume_min, min(info.volume_max, volume)), 2)
    kelly_pct = round(kelly_frac * 100, 2)
    merit = round(min(1.0, (rr / 3.0) * (p / 0.5)), 2)

    return {
        "symbol": symbol,
        "volume": volume,
        "risk_usd": round(risk_usd, 2),
        "reward_usd": round(risk_usd * rr, 2),
        "rr_ratio": rr,
        "kelly_pct": kelly_pct,
        "stop_pts": int(stop_pts),
        "take_pts": int(take_pts),
        "merit_score": merit,
        "validation": "OK",
    }

@mcp.tool()
def validate_trade_signal(ctx: Context, symbol: str, signal_type: str, entry: float,
                          sl: float, tp: float) -> dict:
    """
    Pre-trade validation: spread, stop level, volatility, market hours.
    Parameters:
      symbol: ticker symbol
      signal_type: 'BUY' or 'SELL'
      entry/sl/tp: price levels
    Returns: {valid: bool, checks: {spread, stops, volatility, hours}, reason}
    """
    mt5 = get_mt5()
    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if not info or not tick:
        return {"valid": False, "reason": "No market data"}

    point = info.point
    spread_pts = round((tick.ask - tick.bid) / point)
    checks = {}

    # Spread check — use live spread or symbol spread, not spread_max
    baseline_spread = float(getattr(info, "spread", 50) or 50)
    checks["spread"] = spread_pts <= baseline_spread * 2
    if not checks["spread"]:
        return {"valid": False, "reason": f"Spread {spread_pts}pts > 2x baseline {int(baseline_spread)}pts"}

    # Stop level check — side-aware
    side = signal_type.upper()
    valid_dir, dir_reason = _sltp_valid(symbol, side, entry, sl, tp)
    if not valid_dir:
        return {"valid": False, "reason": dir_reason}

    sl_pts = abs(entry - sl) / point
    checks["stops"] = sl_pts >= info.trade_stops_level
    if not checks["stops"]:
        return {"valid": False, "reason": f"SL {sl_pts:.0f}pts < stop level {info.trade_stops_level}"}

    # Volatility check (ATR)
    df = _get_candles_df(symbol, "M15", 96)
    if not df.empty and "close" in df.columns:
        atr = (df["high"] - df["low"]).rolling(14).mean().iloc[-1]
        atr_pts = atr / point
        checks["volatility"] = sl_pts >= atr_pts * 0.5
        if not checks["volatility"]:
            return {"valid": False, "reason": f"SL {sl_pts:.0f}pts < 0.5x ATR {atr_pts:.0f}pts"}
    else:
        checks["volatility"] = True

    # Market hours (MT5 returns valid ticks only during open hours)
    checks["hours"] = tick.bid > 0 and tick.ask > 0
    if not checks["hours"]:
        return {"valid": False, "reason": "Market closed"}

    total = all(checks.values())
    return {"valid": total, "checks": checks, "reason": "OK" if total else "Validation failed"}

@mcp.tool()
def get_technical_indicators(ctx: Context, symbol: str, timeframe: str = "M15") -> dict:
    """
    Compute technical indicators for a symbol.
    Returns: {rsi, macd, macd_signal, macd_hist, atr, bollinger_upper/lower,
              sma_20/50/200, stochastic_k/d}
    """
    df = _get_candles_df(symbol, timeframe, 300)
    if df.empty or "close" not in df.columns:
        return {"error": f"Not enough data for {symbol}"}

    close = df["close"].values
    high = df["high"].values if "high" in df.columns else close
    low = df["low"].values if "low" in df.columns else close

    def _rsi(series, period=14):
        delta = np.diff(series)
        ups = np.where(delta > 0, delta, 0)
        downs = np.where(delta < 0, -delta, 0)
        avg_gain = pd.Series(ups).rolling(period).mean().iloc[-1] if len(ups) >= period else 50
        avg_loss = pd.Series(downs).rolling(period).mean().iloc[-1] if len(downs) >= period else 1
        rs = avg_gain / avg_loss if avg_loss != 0 else 100
        return round(100 - (100 / (1 + rs)), 1)

    def _macd(series, fast=12, slow=26, signal=9):
        ema_fast = pd.Series(series).ewm(span=fast).mean().iloc[-1]
        ema_slow = pd.Series(series).ewm(span=slow).mean().iloc[-1]
        macd_line = ema_fast - ema_slow
        # Approx signal line (EMA of MACD)
        macd_series = pd.Series(series).ewm(span=fast).mean() - pd.Series(series).ewm(span=slow).mean()
        signal_line = macd_series.ewm(span=signal).mean().iloc[-1]
        return round(macd_line, 5), round(signal_line, 5), round(macd_line - signal_line, 5)

    def _bb(series, period=20, std=2):
        sma = pd.Series(series).rolling(period).mean().iloc[-1]
        stdv = pd.Series(series).rolling(period).std().iloc[-1]
        return round(sma - std * stdv, 5), round(sma, 5), round(sma + std * stdv, 5)

    result = {
        "symbol": symbol,
        "timeframe": timeframe,
        "price": round(float(close[-1]), 5),
        "rsi_14": _rsi(close, 14),
        "macd": {},
        "bollinger": {},
        "sma": {},
        "atr": round(float((high[-14:] - low[-14:]).mean() if len(high) >= 14 else 0), 5),
    }
    macd_l, macd_s, macd_h = _macd(close)
    result["macd"] = {"macd": macd_l, "signal": macd_s, "histogram": macd_h}
    bb_l, bb_m, bb_u = _bb(close)
    result["bollinger"] = {"upper": bb_u, "middle": bb_m, "lower": bb_l}
    for p in [20, 50, 200]:
        if len(close) >= p:
            result["sma"][str(p)] = round(float(pd.Series(close).rolling(p).mean().iloc[-1]), 5)
        else:
            result["sma"][str(p)] = None

    # RSI signal
    rsi = result["rsi_14"]
    if rsi >= 70:
        result["rsi_signal"] = "OVERBOUGHT"
    elif rsi <= 30:
        result["rsi_signal"] = "OVERSOLD"
    else:
        result["rsi_signal"] = "NEUTRAL"

    # MACD signal
    result["macd_signal"] = "BULLISH" if macd_h > 0 else "BEARISH"
    if macd_h > 0 and macd_l > macd_s:
        result["macd_signal"] = "BULLISH_CROSS"
    elif macd_h < 0 and macd_l < macd_s:
        result["macd_signal"] = "BEARISH_CROSS"

    return result

@mcp.tool()
def calculate_symbol_correlation(ctx: Context, symbols: List[str], period: int = 100,
                                 timeframe: str = "H1") -> dict:
    """
    Calculate correlation matrix for a list of symbols.
    Parameters:
      symbols:  list of ticker symbols e.g. ['EURUSD','GBPUSD','USDJPY']
      period:   number of periods (default 100)
      timeframe: timeframe (default H1)
    Returns: {correlation_matrix: {sym1: {sym2: value}}, warnings: [...]}
    """
    prices = {}
    for sym in symbols:
        df = _get_candles_df(sym, timeframe, period)
        if not df.empty and "close" in df.columns:
            prices[sym] = df["close"].values[:period]
    if len(prices) < 2:
        return {"error": "Need at least 2 symbols with data"}

    # Align lengths
    min_len = min(len(v) for v in prices.values())
    aligned = {k: v[:min_len] for k, v in prices.items()}

    df = pd.DataFrame(aligned)
    corr = df.corr().round(3)

    matrix = {}
    warnings = []
    for s1 in symbols:
        matrix[s1] = {}
        for s2 in symbols:
            if s1 in corr.index and s2 in corr.columns:
                val = float(corr.loc[s1, s2]) if s1 != s2 else 1.0
                matrix[s1][s2] = val
            else:
                matrix[s1][s2] = 0.0
            # Flag high correlations
            if s1 != s2 and matrix[s1][s2] > MAX_CORRELATION:
                warnings.append(f"High correlation: {s1} vs {s2} = {matrix[s1][s2]}")

    return {"correlation_matrix": matrix, "warnings": warnings}

@mcp.tool()
def check_news_blackout(ctx: Context, blackout_minutes: int = NEWS_BLACKOUT_MINUTES) -> dict:
    """
    Check if now is in a news blackout period (before/after high-impact econ events today).
    Parameters:
      blackout_minutes: minutes before/after event (default 15)
    Returns: {in_blackout: bool, events_nearby: [{name, time, impact}], reason: str}
    """
    now = datetime.now()
    events = _fetch_calendar(now.strftime('%Y-%m-%d'), usmajor=False)
    if "error" in events[0] if events else True:
        return {"in_blackout": False, "events_nearby": [], "reason": "Cannot fetch calendar"}

    nearby = []
    # Time in NY (ET) - approximate: UTC-4 (EDT) or UTC-5 (EST)
    now_et = now - timedelta(hours=4)
    now_min = now_et.hour * 60 + now_et.minute

    for e in events:
        t_str = e.get("time", "24H")
        if t_str == "24H" or not t_str:
            continue
        try:
            parts = t_str.split(":")
            event_min = int(parts[0]) * 60 + int(parts[1])
            diff = abs(now_min - event_min)
            if diff <= blackout_minutes:
                nearby.append({
                    "event": e.get("eventName"),
                    "time": t_str,
                    "country": e.get("country"),
                    "minutes_until": int(now_min - event_min) if now_min < event_min else int(event_min - now_min),
                    "impact": "HIGH"  # Conservative: all events treated as high impact
                })
        except (ValueError, IndexError):
            continue

    in_blackout = len(nearby) > 0
    return {
        "in_blackout": in_blackout,
        "events_nearby": nearby,
        "reason": "BLACKOUT" if in_blackout else "CLEAR"
    }

@mcp.tool()
def get_portfolio_risk_snapshot(ctx: Context) -> dict:
    """
    Get comprehensive portfolio risk snapshot.
    Returns: {balance, equity, margin, exposure, daily_pnl, positions_risk,
              var_95, correlation_warnings, breaches}
    """
    mt5 = get_mt5()
    acc = mt5.account_info()
    if not acc:
        return {"error": "Cannot get account info"}
    acc = acc._asdict()

    positions = mt5.positions_get()
    pos_list = []
    total_exposure = 0.0
    daily_pnl = 0.0
    symbols_open = []

    if positions:
        for p in positions:
            pnl = float(p.profit) if hasattr(p, 'profit') else 0
            daily_pnl += pnl
            pos_list.append({
                "ticket": p.ticket, "symbol": p.symbol,
                "volume": float(p.volume), "type": "BUY" if p.type == 0 else "SELL",
                "price_open": float(p.price_open),
                "sl": float(p.sl) if p.sl else None,
                "tp": float(p.tp) if p.tp else None,
                "profit": round(pnl, 2),
                "swap": float(p.swap) if hasattr(p, 'swap') else 0,
            })
            total_exposure += float(p.volume) * float(p.price_open)
            symbols_open.append(p.symbol)

    # VaR (simplified: 95% daily)
    equity = float(acc.get("equity", 0))
    balance = float(acc.get("balance", 0))
    var_95 = round(balance * 0.01, 2)  # 1% daily VaR

    # Breaches
    breaches = []
    if total_exposure > balance * MAX_SYMBOL_EXPOSURE * 10:
        breaches.append("Total exposure > 50% of balance")
    if daily_pnl < -balance * MAX_DAILY_LOSS:
        breaches.append(f"Daily loss ${abs(daily_pnl):.0f} > 3% of balance")

    # Correlation check
    corr_warnings = []
    if len(symbols_open) >= 2:
        corr = calculate_symbol_correlation(ctx, symbols_open[:5], 100, "H1")
        if "warnings" in corr:
            corr_warnings = corr["warnings"]

    margin_level = round(float(acc.get("margin_level", 0)), 2) if acc.get("margin_level") else 0

    return {
        "account": {
            "balance": round(balance, 2),
            "equity": round(equity, 2),
            "margin": round(float(acc.get("margin", 0)), 2),
            "margin_level_pct": margin_level,
            "free_margin": round(float(acc.get("margin_free", 0)), 2),
            "leverage": acc.get("leverage"),
        },
        "risk": {
            "daily_pnl": round(daily_pnl, 2),
            "total_exposure": round(total_exposure, 2),
            "exposure_pct": round(total_exposure / balance * 100, 2) if balance else 0,
            "positions_open": len(pos_list),
            "var_95_daily": var_95,
            "margin_safe": margin_level > 100 if margin_level else True,
        },
        "positions": pos_list,
        "breaches": breaches,
        "correlation_warnings": corr_warnings,
        "timestamp": datetime.now().isoformat(),
    }

@mcp.tool()
def get_market_regime(ctx: Context, symbols: List[str], timeframe: str = "H1") -> dict:
    """
    Detect market regime (trend/range) for each symbol.
    Uses ADX and Bollinger Band width.
    Parameters:
      symbols: list of symbols to analyze
      timeframe: timeframe (default H1)
    Returns: {symbol: {regime, adx, bb_width, trend_strength}}
    """
    results = {}
    for sym in symbols:
        df = _get_candles_df(sym, timeframe, 100)
        if df.empty or "close" not in df.columns:
            results[sym] = {"error": "No data"}
            continue
        high = df["high"].values
        low = df["low"].values
        close = df["close"].values

        # ATR-based regime: compare recent range to average
        if len(high) >= 20:
            recent_range = (high[-5:].max() - low[-5:].min())
            avg_range = (high[-20:] - low[-20:]).mean()
            ratio = recent_range / avg_range if avg_range > 0 else 1

            # Bollinger width
            bb_up = pd.Series(close).rolling(20).mean() + 2 * pd.Series(close).rolling(20).std()
            bb_low = pd.Series(close).rolling(20).mean() - 2 * pd.Series(close).rolling(20).std()
            bb_width = (bb_up.iloc[-1] - bb_low.iloc[-1]) / close[-1] if close[-1] > 0 else 0

            if ratio > 1.3 and bb_width > 0.05:
                regime = "TRENDING"
                strength = round(min(ratio / 2, 1.0), 2)
            elif ratio < 0.8 and bb_width < 0.03:
                regime = "RANGING"
                strength = round(1.0 - ratio, 2)
            else:
                regime = "MILD_TREND"
                strength = round(abs(ratio - 1.0), 2)

            results[sym] = {
                "regime": regime,
                "trend_strength": strength,
                "bb_width_pct": round(bb_width * 100, 2),
                "recent_range_ratio": round(ratio, 2),
                "price": round(float(close[-1]), 5),
            }

    return {"regime_analysis": results, "timeframe": timeframe}
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "stdio":
        mcp.run()
    else:
        host = os.environ.get("MCP_HOST", "0.0.0.0")
        port = int(os.environ.get("MCP_PORT", "8080"))
        mcp.run(transport=transport, host=host, port=port)
