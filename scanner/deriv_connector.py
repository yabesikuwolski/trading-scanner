"""Read-only connector for a Deriv demo account and market data."""

import argparse
import json
import logging
import time
from threading import RLock
from urllib.parse import quote

import pandas as pd
import requests
from websockets.sync.client import connect as websocket_connect

import config


REST_BASE_URL = "https://api.derivws.com"
DERIV_SOURCE = "DERIV-DEMO"
GRANULARITY_MAP = {"M15": 900, "H1": 3600, "H4": 14400}
_lock = RLock()
_socket = None
_demo_account = None
_request_id = 0
_gold_symbol = None


def _headers():
    token = config.DERIV_API_TOKEN
    app_id = config.DERIV_APP_ID
    if not token or not app_id:
        raise RuntimeError(
            "Set DERIV_API_TOKEN and DERIV_APP_ID in the local .env before using the Deriv demo connector."
        )
    return {
        "Authorization": f"Bearer {token}",
        "Deriv-App-ID": app_id,
        "Content-Type": "application/json",
    }


def _rest_json(method, path):
    try:
        response = requests.request(
            method,
            f"{REST_BASE_URL}{path}",
            headers=_headers(),
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        suffix = f" (HTTP {status})" if status else ""
        raise RuntimeError(f"Deriv authentication request failed{suffix}.") from None
    except ValueError:
        raise RuntimeError("Deriv returned an invalid JSON response.") from None

    errors = payload.get("errors") or payload.get("error")
    if errors:
        raise RuntimeError("Deriv rejected the read-only demo account request.")
    return payload.get("data", payload)


def _accounts_from_response(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("accounts", "items", "data"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return rows
            if isinstance(rows, dict):
                nested = rows.get("accounts") or rows.get("items")
                if isinstance(nested, list):
                    return nested
    return []


def _account_type(account):
    value = account.get("account_type") or account.get("type") or ""
    if str(value).lower() == "demo" or account.get("is_virtual") is True:
        return "demo"
    return str(value).lower()


def _select_demo_account(accounts):
    demo_accounts = [account for account in accounts if _account_type(account) == "demo"]
    requested_id = config.DERIV_DEMO_ACCOUNT_ID
    if requested_id:
        selected = next(
            (account for account in demo_accounts if str(account.get("account_id", "")) == requested_id),
            None,
        )
        if selected is None:
            raise RuntimeError("Configured Deriv account is not an available demo account.")
        return selected
    if not demo_accounts:
        raise RuntimeError("No Deriv demo Options account is available for this token.")
    return demo_accounts[0]


def connect():
    """Connect to an Options demo account only; this connector never places trades."""
    global _socket, _demo_account, _gold_symbol
    with _lock:
        _headers()
        accounts_payload = _rest_json("GET", "/trading/v1/options/accounts")
        _demo_account = _select_demo_account(_accounts_from_response(accounts_payload))
        account_id = str(_demo_account.get("account_id", ""))
        if not account_id:
            raise RuntimeError("Deriv demo account response did not include an account ID.")

        otp_payload = _rest_json(
            "POST",
            f"/trading/v1/options/accounts/{quote(account_id, safe='')}/otp",
        )
        websocket_url = otp_payload.get("url")
        if not isinstance(websocket_url, str) or not websocket_url.startswith(
            "wss://api.derivws.com/trading/v1/options/ws/demo?"
        ):
            raise RuntimeError("Deriv did not return a demo-scoped WebSocket URL.")

        try:
            _socket = websocket_connect(
                websocket_url,
                open_timeout=15,
                close_timeout=5,
                ping_interval=20,
                ping_timeout=20,
            )
        except Exception:
            _socket = None
            raise RuntimeError("Could not open the Deriv demo WebSocket.") from None
        _gold_symbol = None
        return True


def disconnect():
    global _socket, _demo_account, _gold_symbol
    with _lock:
        if _socket is not None:
            try:
                _socket.close()
            finally:
                _socket = None
        _demo_account = None
        _gold_symbol = None


def _request(payload):
    global _request_id
    last_error = None

    for attempt in range(2):
        try:
            if _socket is None:
                connect()

            with _lock:
                _request_id += 1
                request_id = _request_id
                message = {**payload, "req_id": request_id}
                _socket.send(json.dumps(message))
                while True:
                    response = json.loads(_socket.recv(timeout=15))
                    if response.get("req_id") not in (None, request_id):
                        continue
                    if response.get("error"):
                        code = response["error"].get("code", "APIError")
                        raise RuntimeError(f"Deriv rejected a read-only data request ({code}).")
                    return response
        except (RuntimeError, TimeoutError, ConnectionError, OSError):
            last_error = RuntimeError("Deriv WebSocket request failed or timed out.")
            try:
                disconnect()
            except Exception:
                pass
            if attempt == 0:
                try:
                    connect()
                except Exception:
                    pass
                continue
            raise last_error from None
        except Exception as exc:
            last_error = exc
            try:
                disconnect()
            except Exception:
                pass
            if attempt == 0:
                try:
                    connect()
                except Exception:
                    pass
                continue
            raise RuntimeError("Deriv WebSocket request failed or timed out.") from exc

    raise RuntimeError("Deriv WebSocket request failed or timed out.") from last_error


def get_account_info():
    """Return demo balance metadata for risk checks; never returns credentials."""
    if _demo_account is None:
        return {}
    response = _request({"balance": 1})
    balance_data = response.get("balance")
    if not isinstance(balance_data, dict) or balance_data.get("balance") is None:
        raise RuntimeError("Deriv demo balance response was incomplete.")
    balance = float(balance_data["balance"])
    return {
        "balance": balance,
        "equity": balance,
        "currency": balance_data.get("currency", _demo_account.get("currency", "")),
        "account_type": "demo",
    }


def _resolve_gold_symbol():
    global _gold_symbol
    if _gold_symbol:
        return _gold_symbol
    response = _request({"active_symbols": "brief"})
    symbols = response.get("active_symbols") or []

    def _gold_match(item):
        fields = [
            str(item.get("symbol", "") or ""),
            str(item.get("underlying_symbol", "") or ""),
            str(item.get("display_name", "") or ""),
            str(item.get("underlying_symbol_name", "") or ""),
        ]
        text = " ".join(fields).lower()
        return "gold" in text or "xau" in text

    gold = [item for item in symbols if _gold_match(item)]
    if gold:
        def _sort_key(item):
            symbol = str(item.get("underlying_symbol") or item.get("symbol") or "").lower()
            return (
                0 if symbol == "frxxauusd" else 1 if symbol == "wldxau" else 2,
                symbol,
            )

        gold.sort(key=_sort_key)
        _gold_symbol = str(gold[0].get("underlying_symbol") or gold[0].get("symbol") or "")
        if _gold_symbol:
            return _gold_symbol

    for candidate in ("frxXAUUSD", "WLDXAU", "OTC_XAUUSD", "XAUUSD"):
        try:
            _request({
                "ticks_history": candidate,
                "end": "latest",
                "count": 1,
                "style": "candles",
                "granularity": GRANULARITY_MAP["M15"],
            })
            _gold_symbol = candidate
            return _gold_symbol
        except RuntimeError:
            continue

    raise RuntimeError("Deriv did not list an available Gold/XAU market symbol.")


def get_bars(symbol, timeframe, count=200):
    """Fetch normalized UTC candles; requested XAUUSD maps to Deriv's Gold symbol."""
    timeframe = timeframe.upper()
    if timeframe not in GRANULARITY_MAP:
        raise ValueError("Supported Deriv timeframes are M15, H1, and H4.")
    if not 1 <= count <= 5000:
        raise ValueError("Candle count must be between 1 and 5000.")
    if symbol.upper() not in {"XAUUSD", "XAU_USD", "GOLD"}:
        raise ValueError("The read-only Deriv connector is configured for XAU/USD Gold only.")

    deriv_symbol = _resolve_gold_symbol()
    response = _request({
        "ticks_history": deriv_symbol,
        "end": "latest",
        "count": count,
        "style": "candles",
        "granularity": GRANULARITY_MAP[timeframe],
    })
    candles = response.get("candles") or []
    if not candles:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

    frame = pd.DataFrame(candles)
    frame["time"] = pd.to_datetime(frame["epoch"], unit="s", utc=True, errors="coerce")
    frame = frame.dropna(subset=["time"]).set_index("time").sort_index()
    for column in ("open", "high", "low", "close"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["Volume"] = 0
    frame.rename(columns={
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
    }, inplace=True)
    frame = frame.dropna(subset=["Open", "High", "Low", "Close"])
    return frame[["Open", "High", "Low", "Close", "Volume"]]


def get_symbol_info(symbol):
    if symbol.upper() not in {"XAUUSD", "XAU_USD", "GOLD"}:
        return {}
    deriv_symbol = _resolve_gold_symbol()
    return {"symbol": deriv_symbol, "account_type": "demo"}


def main():
    parser = argparse.ArgumentParser(description="Check Deriv demo account and read-only Gold candles")
    parser.add_argument("--timeframes", nargs="+", choices=GRANULARITY_MAP, default=["H4", "H1", "M15"])
    parser.add_argument("--count", type=int, default=5)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    connect()
    try:
        account = get_account_info()
        print(f"Deriv account: DEMO | balance: {account['balance']:.2f} {account['currency']}")
        for timeframe in args.timeframes:
            bars = get_bars("XAUUSD", timeframe, args.count)
            if bars.empty:
                print(f"{timeframe}: no candles returned")
                continue
            print(
                f"{timeframe}: {len(bars)} Gold candles; latest close={bars.iloc[-1]['Close']}; "
                f"bar time={bars.index[-1].isoformat()}"
            )
    finally:
        disconnect()


if __name__ == "__main__":
    main()