import json
import unittest
from unittest.mock import Mock, patch

import config
from scanner import deriv_connector


class FakeSocket:
    def __init__(self):
        self.last_request = None
        self.closed = False

    def send(self, message):
        self.last_request = json.loads(message)

    def recv(self, timeout=None):
        request = self.last_request
        req_id = request["req_id"]
        if "balance" in request:
            response = {
                "msg_type": "balance",
                "req_id": req_id,
                "balance": {"balance": 12500.5, "currency": "USD"},
            }
        elif "active_symbols" in request:
            response = {
                "msg_type": "active_symbols",
                "req_id": req_id,
                "active_symbols": [
                    {"symbol": "OTC_XAUUSD", "display_name": "Gold (OTC)"},
                    {"symbol": "frxXAUUSD", "display_name": "Gold/USD"},
                ],
            }
        elif "ticks_history" in request:
            response = {
                "msg_type": "candles",
                "req_id": req_id,
                "candles": [
                    {"epoch": 1790928000, "open": "4000", "high": "4010", "low": "3990", "close": "4005"},
                    {"epoch": 1790928900, "open": "4005", "high": "4020", "low": "4000", "close": "4015"},
                ],
            }
        else:
            response = {"req_id": req_id, "error": {"code": "InvalidRequest"}}
        return json.dumps(response)

    def close(self):
        self.closed = True


class TimeoutOnceSocket(FakeSocket):
    def __init__(self):
        super().__init__()
        self.calls = 0

    def recv(self, timeout=None):
        self.calls += 1
        if self.calls == 1:
            raise TimeoutError("timed out while waiting for response")
        return super().recv(timeout)


class DerivConnectorTests(unittest.TestCase):
    def tearDown(self):
        deriv_connector.disconnect()

    def test_request_reconnects_after_stale_socket_timeout(self):
        stale = TimeoutOnceSocket()
        fresh = FakeSocket()

        with patch.object(deriv_connector, "_socket", stale), \
             patch.object(deriv_connector, "_demo_account", {"account_id": "DEMO-2", "currency": "USD"}), \
             patch.object(deriv_connector, "connect", side_effect=lambda: setattr(deriv_connector, "_socket", fresh) or None), \
             patch.object(deriv_connector, "disconnect", side_effect=lambda: setattr(deriv_connector, "_socket", None)):
            response = deriv_connector._request({"balance": 1})
            self.assertEqual(response["balance"]["balance"], 12500.5)
            self.assertIs(deriv_connector._socket, fresh)

    def test_requires_token_and_app_id_before_network(self):
        with patch.object(config, "DERIV_API_TOKEN", ""), patch.object(config, "DERIV_APP_ID", ""):
            with patch("scanner.deriv_connector.requests.request") as request:
                with self.assertRaisesRegex(RuntimeError, "DERIV_API_TOKEN"):
                    deriv_connector.connect()
        request.assert_not_called()

    def test_refuses_real_account(self):
        with self.assertRaisesRegex(RuntimeError, "No Deriv demo"):
            deriv_connector._select_demo_account([
                {"account_id": "REAL-123", "account_type": "real"},
            ])

    @patch("scanner.deriv_connector._request")
    def test_resolves_gold_market_from_underlying_symbol_field(self, request):
        request.return_value = {
            "active_symbols": [
                {"underlying_symbol": "WLDXAU", "underlying_symbol_name": "Gold Basket"},
                {"underlying_symbol": "frxXAUUSD", "underlying_symbol_name": "Gold/USD"},
            ]
        }
        with patch.object(deriv_connector, "_gold_symbol", None):
            self.assertEqual(deriv_connector._resolve_gold_symbol(), "frxXAUUSD")

    @patch("scanner.deriv_connector.websocket_connect")
    @patch("scanner.deriv_connector.requests.request")
    def test_demo_connect_balance_and_normalized_gold_bars(self, request, ws_connect):
        accounts_response = Mock()
        accounts_response.raise_for_status.return_value = None
        accounts_response.json.return_value = {
            "data": {"accounts": [
                {"account_id": "REAL-1", "account_type": "real", "currency": "USD"},
                {"account_id": "DEMO-2", "account_type": "demo", "currency": "USD"},
            ]}
        }
        otp_response = Mock()
        otp_response.raise_for_status.return_value = None
        otp_response.json.return_value = {
            "data": {"url": "wss://api.derivws.com/trading/v1/options/ws/demo?otp=one-time"}
        }
        request.side_effect = [accounts_response, otp_response]
        fake_socket = FakeSocket()
        ws_connect.return_value = fake_socket

        with patch.object(config, "DERIV_API_TOKEN", "test-token"), \
             patch.object(config, "DERIV_APP_ID", "99999"), \
             patch.object(config, "DERIV_DEMO_ACCOUNT_ID", ""):
            deriv_connector.connect()
            account = deriv_connector.get_account_info()
            bars = deriv_connector.get_bars("XAUUSD", "M15", 2)

        self.assertEqual(account["balance"], 12500.5)
        self.assertEqual(account["equity"], 12500.5)
        self.assertEqual(account["currency"], "USD")
        self.assertEqual(account["account_type"], "demo")
        self.assertEqual(list(bars.columns), ["Open", "High", "Low", "Close", "Volume"])
        self.assertTrue(bars.index.is_monotonic_increasing)
        self.assertEqual(len(bars), 2)
        self.assertEqual(bars.iloc[-1]["Close"], 4015.0)
        self.assertEqual(fake_socket.last_request["ticks_history"], "frxXAUUSD")
        self.assertEqual(ws_connect.call_args.args[0], otp_response.json.return_value["data"]["url"])
        self.assertIn("/DEMO-2/otp", request.call_args_list[1].args[1])


if __name__ == "__main__":
    unittest.main()