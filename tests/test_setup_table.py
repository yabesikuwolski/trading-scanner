import unittest

from dashboard.setup_table import build_active_setups_table


class ActiveSetupsTableTests(unittest.TestCase):
    def test_signal_type_is_included_in_table(self):
        table = build_active_setups_table([{
            "symbol": "XAUUSD",
            "grade": "A",
            "signal_type": "BUY LIMIT",
        }])

        self.assertIn("signal_type", table.columns)
        self.assertEqual(table.loc[0, "signal_type"], "BUY LIMIT")

    def test_missing_legacy_signal_type_is_labeled(self):
        table = build_active_setups_table([{
            "symbol": "XAUUSD",
            "grade": "A",
        }])

        self.assertIn("signal_type", table.columns)
        self.assertEqual(table.loc[0, "signal_type"], "Not recorded")

    def test_null_migrated_signal_type_is_labeled(self):
        table = build_active_setups_table([{
            "symbol": "XAUUSD",
            "grade": "A",
            "signal_type": None,
        }])

        self.assertEqual(table.loc[0, "signal_type"], "Not recorded")


if __name__ == "__main__":
    unittest.main()