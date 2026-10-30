import unittest
from unittest.mock import patch

import config
import main


class MainResilienceTests(unittest.TestCase):
    def test_startup_and_scan_failures_retry_without_ending_service_loop(self):
        with (
            patch("main.init_db"),
            patch("main.connect", side_effect=[RuntimeError("temporary outage"), None]) as connect,
            patch("main.disconnect") as disconnect,
            patch.object(config, "SCAN_INTERVAL", 1),
            patch.object(config, "NEWS_FILTER_ENABLED", False),
            patch("main.send_alert") as send_alert,
            patch("main.time.sleep") as sleep,
            patch("main.scan_once", side_effect=[RuntimeError("temporary scan error"), KeyboardInterrupt]) as scan_once,
        ):
            main.main()

        self.assertEqual(connect.call_count, 2)
        self.assertEqual(scan_once.call_count, 2)
        self.assertEqual(sleep.call_count, 2)
        disconnect.assert_called_once()
        send_alert.assert_not_called()


if __name__ == "__main__":
    unittest.main()
