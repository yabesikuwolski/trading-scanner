import unittest
from unittest.mock import patch

import config
from risk.risk_manager import RiskManager


class RiskModelTests(unittest.TestCase):
    def test_example_a_risk_and_rr_are_calculated_from_10_balance(self):
        manager = RiskManager()
        plan = manager.calculate_trade_plan(
            account_balance=10.0,
            entry=4182.23,
            sl=4176.76,
            risk_pct=2.0,
            rr_multiple=2.0,
        )

        self.assertAlmostEqual(plan["risk_amount"], 0.20, places=4)
        self.assertAlmostEqual(plan["expected_profit"], 0.40, places=4)
        self.assertIsNone(plan["position_size"])
        self.assertEqual(plan["sizing_status"], "MISSING_CONTRACT_SPECS")

    def test_example_b_losing_trade_reduces_equity_by_risk_amount(self):
        manager = RiskManager()
        plan = manager.calculate_trade_plan(
            account_balance=10.0,
            entry=4182.23,
            sl=4176.76,
            risk_pct=2.0,
            rr_multiple=2.0,
        )

        result = manager.apply_trade_result(10.0, plan, outcome="loss")
        self.assertAlmostEqual(result, 9.80, places=4)

    def test_example_c_winning_trade_reaches_2r(self):
        manager = RiskManager()
        plan = manager.calculate_trade_plan(
            account_balance=10.0,
            entry=4182.23,
            sl=4176.76,
            risk_pct=2.0,
            rr_multiple=2.0,
        )

        result = manager.apply_trade_result(10.0, plan, outcome="win", rr_achieved=2.0)
        self.assertAlmostEqual(result, 10.40, places=4)

    def test_example_d_simulation_balance_change_updates_risk_automatically(self):
        manager = RiskManager()
        ten_plan = manager.calculate_trade_plan(
            account_balance=10.0,
            entry=4182.23,
            sl=4176.76,
            risk_pct=2.0,
            rr_multiple=2.0,
        )
        twenty_plan = manager.calculate_trade_plan(
            account_balance=20.0,
            entry=4182.23,
            sl=4176.76,
            risk_pct=2.0,
            rr_multiple=2.0,
        )

        self.assertAlmostEqual(ten_plan["risk_amount"], 0.20, places=4)
        self.assertAlmostEqual(twenty_plan["risk_amount"], 0.40, places=4)
        self.assertAlmostEqual(twenty_plan["expected_profit"], 0.80, places=4)

    def test_position_size_uses_contract_value_and_rounds_down_to_volume_step(self):
        manager = RiskManager()
        plan = manager.calculate_trade_plan(
            account_balance=1000.0,
            entry=4200.0,
            sl=4195.0,
            risk_pct=2.0,
            contract_size=100.0,
            broker_min_volume=0.01,
            broker_volume_step=0.01,
            broker_max_volume=100.0,
        )

        self.assertEqual(plan["sizing_status"], "OK")
        self.assertAlmostEqual(plan["required_volume"], 0.04)
        self.assertAlmostEqual(plan["position_size"], 0.04)
        self.assertAlmostEqual(plan["actual_risk"], 20.0)
        self.assertEqual(plan["risk_sizing_feasibility"], "WITHIN_CONFIGURED_RISK")
        self.assertEqual(plan["account_feasibility"], "UNKNOWN")
        self.assertEqual(plan["margin_status"], "unavailable")

    def test_ten_dollar_risk_below_broker_minimum_is_not_rounded_up(self):
        manager = RiskManager()
        plan = manager.calculate_trade_plan(
            account_balance=10.0,
            entry=4200.0,
            sl=4195.0,
            risk_pct=2.0,
            contract_size=100.0,
            broker_min_volume=0.01,
            broker_volume_step=0.01,
            broker_max_volume=100.0,
        )

        self.assertAlmostEqual(plan["risk_amount"], 0.20)
        self.assertAlmostEqual(plan["required_volume"], 0.0004)
        self.assertIsNone(plan["position_size"])
        self.assertEqual(plan["sizing_status"], "BELOW_BROKER_MINIMUM")

    def test_volume_steps_are_anchored_at_broker_minimum_and_capped_safely(self):
        manager = RiskManager()
        plan = manager.calculate_trade_plan(
            account_balance=100.0,
            entry=100.0,
            sl=99.0,
            risk_pct=2.0,
            contract_size=100.0,
            broker_min_volume=0.03,
            broker_volume_step=0.02,
            broker_max_volume=0.08,
        )

        # Required volume is 0.02, below the minimum, so no volume is invented.
        self.assertEqual(plan["sizing_status"], "BELOW_BROKER_MINIMUM")
        self.assertIsNone(plan["position_size"])

    def test_non_aligned_volume_flooring_never_exceeds_risk_budget(self):
        manager = RiskManager()
        plan = manager.calculate_trade_plan(
            account_balance=100.0,
            entry=100.0,
            sl=99.0,
            risk_pct=5.0,
            contract_size=100.0,
            broker_min_volume=0.03,
            broker_volume_step=0.02,
            broker_max_volume=0.08,
        )

        # Required volume 0.05 is valid on the min + N*step ladder.
        self.assertEqual(plan["sizing_status"], "OK")
        self.assertAlmostEqual(plan["position_size"], 0.05)
        self.assertAlmostEqual(plan["actual_risk"], 5.0)
        self.assertAlmostEqual(plan["sized_expected_profit"], 10.0)

    def test_max_volume_is_floored_to_a_valid_step(self):
        manager = RiskManager()
        plan = manager.calculate_trade_plan(
            account_balance=1000.0,
            entry=100.0,
            sl=99.0,
            risk_pct=50.0,
            contract_size=10.0,
            broker_min_volume=0.03,
            broker_volume_step=0.02,
            broker_max_volume=0.08,
        )

        self.assertEqual(plan["sizing_status"], "OK")
        self.assertAlmostEqual(plan["position_size"], 0.07)
        self.assertLessEqual(plan["actual_risk"], plan["risk_amount"])

    def test_invalid_balance_risk_and_volume_rules_are_reported(self):
        manager = RiskManager()
        invalid_balance = manager.calculate_trade_plan(0, 100, 99)
        invalid_risk = manager.calculate_trade_plan(100, 100, 99, risk_pct=0)
        invalid_rules = manager.calculate_trade_plan(
            100, 100, 99, contract_size=100, broker_min_volume=0.01,
            broker_volume_step=0.01, broker_max_volume=0.005,
        )

        self.assertEqual(invalid_balance["sizing_status"], "INVALID_ACCOUNT_BALANCE")
        self.assertEqual(invalid_risk["sizing_status"], "INVALID_RISK_PERCENTAGE")
        self.assertEqual(invalid_rules["sizing_status"], "INVALID_BROKER_VOLUME_RULES")

    def test_one_hundred_dollar_balance_and_stop_distance_change_risk_math(self):
        manager = RiskManager()
        narrow_stop = manager.calculate_trade_plan(
            account_balance=100.0, entry=4200.0, sl=4195.0, risk_pct=2.0,
            contract_size=100.0, broker_min_volume=0.01, broker_volume_step=0.01,
        )
        wide_stop = manager.calculate_trade_plan(
            account_balance=100.0, entry=4200.0, sl=4190.0, risk_pct=2.0,
            contract_size=100.0, broker_min_volume=0.01, broker_volume_step=0.01,
        )
        self.assertAlmostEqual(narrow_stop["risk_amount"], 2.0)
        self.assertAlmostEqual(narrow_stop["expected_profit"], 4.0)
        self.assertAlmostEqual(narrow_stop["required_volume"], 0.004)
        self.assertAlmostEqual(wide_stop["required_volume"], 0.002)
        self.assertEqual(narrow_stop["sizing_status"], "BELOW_BROKER_MINIMUM")

    def test_non_usd_account_requires_currency_conversion_for_reliable_size(self):
        manager = RiskManager()
        with patch.object(config, "SIMULATION_ACCOUNT_CURRENCY", "EUR"):
            plan = manager.calculate_trade_plan(
                account_balance=1000, entry=4200, sl=4195, risk_pct=2,
                contract_size=100, broker_min_volume=0.01, broker_volume_step=0.01,
            )
        self.assertEqual(plan["sizing_status"], "ACCOUNT_CURRENCY_CONVERSION_UNAVAILABLE")
        self.assertEqual(plan["account_feasibility"], "UNKNOWN")
        self.assertIsNone(plan["position_size"])


if __name__ == "__main__":
    unittest.main()
