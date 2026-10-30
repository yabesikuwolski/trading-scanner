from datetime import date
import math
import config
from database.db_manager import get_recent_losses, init_db


class RiskManager:
    def __init__(self):
        self._daily_start = None
        self._weekly_start = None
        self._today = date.today()

    def calculate_trade_plan(
        self,
        account_balance,
        entry,
        sl,
        risk_pct=None,
        rr_multiple=None,
        contract_size=None,
        broker_min_volume=None,
        broker_volume_step=None,
        broker_max_volume=None,
    ):
        """Build a simulation plan; never round an undersized order up to broker minimum."""
        risk_pct = config.MAX_RISK_PER_TRADE if risk_pct is None else float(risk_pct)
        rr_multiple = config.SIMULATION_RR_MULTIPLE if rr_multiple is None else float(rr_multiple)
        contract_size = config.XAUUSD_CONTRACT_SIZE if contract_size is None else float(contract_size)
        broker_min_volume = config.BROKER_MIN_VOLUME if broker_min_volume is None else float(broker_min_volume)
        broker_volume_step = config.BROKER_VOLUME_STEP if broker_volume_step is None else float(broker_volume_step)
        broker_max_volume = config.BROKER_MAX_VOLUME if broker_max_volume is None else float(broker_max_volume)
        account_balance = float(account_balance)
        entry = float(entry)
        sl = float(sl)
        stop_distance = abs(entry - sl) if math.isfinite(entry) and math.isfinite(sl) else 0.0
        valid_balance = math.isfinite(account_balance) and account_balance > 0
        valid_risk = math.isfinite(risk_pct) and 0 < risk_pct <= 100
        valid_rr = math.isfinite(rr_multiple) and rr_multiple > 0
        risk_amount = account_balance * (risk_pct / 100.0) if valid_balance and valid_risk else 0.0
        expected_profit = risk_amount * rr_multiple if valid_rr else 0.0
        required_volume = None
        position_size = None
        actual_risk = None
        sized_expected_profit = None
        if not valid_balance:
            sizing_status = "INVALID_ACCOUNT_BALANCE"
        elif not valid_risk:
            sizing_status = "INVALID_RISK_PERCENTAGE"
        elif not valid_rr:
            sizing_status = "INVALID_RR_MULTIPLE"
        elif stop_distance <= 0:
            sizing_status = "INVALID_STOP_DISTANCE"
        elif str(config.SIMULATION_ACCOUNT_CURRENCY).upper() != "USD":
            sizing_status = "ACCOUNT_CURRENCY_CONVERSION_UNAVAILABLE"
        elif contract_size is not None and (not math.isfinite(contract_size) or contract_size <= 0):
            sizing_status = "INVALID_CONTRACT_SIZE"
        elif contract_size is None:
            sizing_status = "MISSING_CONTRACT_SPECS"
        elif contract_size > 0:
            risk_per_lot = stop_distance * contract_size
            required_volume = risk_amount / risk_per_lot
            if broker_min_volume is None or broker_volume_step is None:
                sizing_status = "MISSING_BROKER_VOLUME_RULES"
            elif (not math.isfinite(broker_min_volume) or not math.isfinite(broker_volume_step)
                  or broker_min_volume <= 0 or broker_volume_step <= 0
                  or (broker_max_volume is not None and (
                      not math.isfinite(broker_max_volume) or broker_max_volume < broker_min_volume
                  ))):
                sizing_status = "INVALID_BROKER_VOLUME_RULES"
            elif required_volume < broker_min_volume:
                sizing_status = "BELOW_BROKER_MINIMUM"
            else:
                volume_cap = min(required_volume, broker_max_volume) if broker_max_volume is not None else required_volume
                volume_steps = math.floor((volume_cap - broker_min_volume + 1e-12) / broker_volume_step)
                position_size = broker_min_volume + volume_steps * broker_volume_step
                if position_size < broker_min_volume:
                    position_size = None
                    sizing_status = "BELOW_BROKER_MINIMUM"
                else:
                    actual_risk = position_size * risk_per_lot
                    sizing_status = "OK" if actual_risk <= risk_amount + 1e-8 else "VOLUME_STEP_EXCEEDS_RISK"
                    if sizing_status != "OK":
                        position_size = None
                        actual_risk = None
                    else:
                        sized_expected_profit = actual_risk * rr_multiple

        if sizing_status == "OK":
            risk_sizing_feasibility = "WITHIN_CONFIGURED_RISK"
            # Margin and symbol settings are not independently verified by this scanner.
            account_feasibility = "UNKNOWN"
        elif sizing_status in {
            "MISSING_CONTRACT_SPECS", "MISSING_BROKER_VOLUME_RULES",
            "ACCOUNT_CURRENCY_CONVERSION_UNAVAILABLE",
        }:
            risk_sizing_feasibility = "UNKNOWN"
            account_feasibility = "UNKNOWN"
        else:
            risk_sizing_feasibility = "INFEASIBLE"
            account_feasibility = "INFEASIBLE"

        return {
            "account_balance": account_balance,
            "currency": config.SIMULATION_ACCOUNT_CURRENCY,
            "risk_pct": float(risk_pct),
            "risk_amount": round(risk_amount, 4),
            "rr_multiple": float(rr_multiple),
            "expected_profit": round(expected_profit, 4),
            "sized_expected_profit": round(sized_expected_profit, 4) if sized_expected_profit is not None else None,
            "stop_distance": round(stop_distance, 5),
            "contract_size": contract_size,
            "required_volume": round(required_volume, 8) if required_volume is not None else None,
            "position_size": round(position_size, 8) if position_size is not None else None,
            "actual_risk": round(actual_risk, 4) if actual_risk is not None else None,
            "broker_min_volume": broker_min_volume,
            "broker_volume_step": broker_volume_step,
            "broker_max_volume": broker_max_volume,
            "sizing_status": sizing_status,
            "risk_sizing_feasibility": risk_sizing_feasibility,
            "account_feasibility": account_feasibility,
            "symbol_specs_verification": (
                "user_configured_unverified"
                if contract_size is not None and broker_min_volume is not None and broker_volume_step is not None
                else "unavailable"
            ),
            "margin_status": "unavailable",
        }

    def apply_trade_result(self, account_balance, trade_plan, outcome, rr_achieved=0.0):
        """Apply a closed journal outcome to strategy equity, not broker equity."""
        risk_amount = float(trade_plan.get("risk_amount", 0.0))
        if outcome == "loss":
            pnl = -risk_amount
        elif outcome == "win":
            pnl = risk_amount * float(rr_achieved)
        else:
            pnl = 0.0
        return round(float(account_balance) + pnl, 4)

    def _reset_if_new_day(self, balance):
        today = date.today()
        if self._today != today:
            self._daily_start = balance
            self._today = today

    def seed_balance(self, balance):
        if self._daily_start is None:
            self._daily_start = balance
        if self._weekly_start is None:
            self._weekly_start = balance

    def check_risk(self, balance, equity, daily_start=None, weekly_start=None):
        init_db()
        self.seed_balance(balance)
        self._reset_if_new_day(balance)
        if daily_start is not None:
            self._daily_start = float(daily_start)
        if weekly_start is not None:
            self._weekly_start = float(weekly_start)

        violations = []
        warnings = []

        daily_dd = max(0.0, (self._daily_start - equity) / self._daily_start * 100)
        weekly_dd = max(0.0, (self._weekly_start - equity) / self._weekly_start * 100)

        if daily_dd >= config.MAX_DAILY_DRAWDOWN:
            violations.append(
                f"Daily drawdown {daily_dd:.2f}% exceeds limit ({config.MAX_DAILY_DRAWDOWN}%)"
            )
        elif daily_dd >= config.MAX_DAILY_DRAWDOWN * 0.75:
            warnings.append(f"Daily drawdown at {daily_dd:.2f}% — approaching limit")

        if weekly_dd >= config.MAX_WEEKLY_DRAWDOWN:
            violations.append(
                f"Weekly drawdown {weekly_dd:.2f}% exceeds limit ({config.MAX_WEEKLY_DRAWDOWN}%)"
            )

        consec_losses = len(get_recent_losses(config.MAX_CONSECUTIVE_LOSSES))
        if consec_losses >= config.MAX_CONSECUTIVE_LOSSES:
            violations.append(
                f"{consec_losses} consecutive losses — trading suspended per constitution"
            )

        return {
            "allowed": len(violations) == 0,
            "violations": violations,
            "warnings": warnings,
            "daily_drawdown": round(daily_dd, 2),
            "weekly_drawdown": round(weekly_dd, 2),
            "consecutive_losses": consec_losses,
            "daily_start": self._daily_start,
            "weekly_start": self._weekly_start,
        }

    def is_elite_trade_allowed(self, scoring, risk_status):
        """Elite trades require ELITE grade + no violations."""
        return (
            scoring.get("grade") == "ELITE"
            and risk_status.get("allowed")
            and risk_status.get("daily_drawdown", 99) < config.MAX_DAILY_DRAWDOWN * 0.5
        )
