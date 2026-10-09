import unittest

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


if __name__ == "__main__":
    unittest.main()
