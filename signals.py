"""
Signal classifier — feeds market state to Jev, gets typed decisions.
The core decision engine.
"""
import json
import time
import math
from typing import Optional


class SignalClassifier:
    """Uses Jev to classify crypto market signals."""

    def __init__(self, jev_client, min_confidence: float = 0.70, min_edge: float = 0.08):
        self.jev = jev_client
        self.min_confidence = min_confidence
        self.min_edge = min_edge

    def classify(self, state: str, asset: str) -> dict:
        """
        Classify a market state into a trading signal.

        Returns:
            {
                "asset": str,
                "regime": str (trending-up/trending-down/ranging/breakout/breakdown),
                "regime_confidence": float,
                "action": str (strong-buy/buy/hold/sell/strong-sell),
                "action_confidence": float,
                "risk_level": float (0-1),
                "should_trade": bool,
                "reasoning": str,
                "raw_answers": list,
            }
        """
        questions = [
            {
                "type": "choice",
                "instructions": f"Based on the market data for {asset}, what is the current market regime?",
                "options": ["trending-up", "trending-down", "ranging", "breakout", "breakdown"],
            },
            {
                "type": "choice",
                "instructions": f"What trading action should be taken for {asset} right now?",
                "options": ["strong-buy", "buy", "hold", "sell", "strong-sell"],
            },
            {
                "type": "score",
                "instructions": f"How risky is it to open a new position in {asset} right now? 0=safe, 4=extreme risk.",
                "options": ["very-low", "low", "medium", "high", "extreme"],
            },
            {
                "type": "noul",
                "instructions": f"The current price movement of {asset} is driven by genuine market demand, not a temporary spike or manipulation.",
            },
            {
                "type": "noul",
                "instructions": f"There is a high probability that {asset} will be higher in 24 hours than it is now.",
            },
            {
                "type": "noul",
                "instructions": f"The market for {asset} is overbought — prices have risen too far too fast and are likely to correct.",
            },
            {
                "type": "noul",
                "instructions": f"A price pullback for {asset} is likely within the next 4 hours.",
            },
        ]

        try:
            answers = self.jev.decide(state, questions)
        except Exception as e:
            return self._error_result(asset, str(e))

        # Parse answers
        regime = answers[0] if len(answers) > 0 else {}
        action = answers[1] if len(answers) > 1 else {}
        risk = answers[2] if len(answers) > 2 else {}
        genuine = answers[3] if len(answers) > 3 else {}
        higher_24h = answers[4] if len(answers) > 4 else {}
        overbought = answers[5] if len(answers) > 5 else {}
        pullback = answers[6] if len(answers) > 6 else {}

        regime_str = regime.get("choice", "unknown")
        regime_conf = regime.get("confidence", 0.0)
        action_str = action.get("choice", "hold")
        action_conf = action.get("confidence", 0.0)
        risk_score = risk.get("score", 2.0) / 4.0  # normalize to 0-1
        genuine_prob = genuine.get("noul", 0.5)
        higher_prob = higher_24h.get("noul", 0.5)
        overbought_prob = overbought.get("noul", 0.5)
        pullback_prob = pullback.get("noul", 0.5)

        # Decision logic
        should_trade = (
            action_conf >= self.min_confidence
            and genuine_prob >= 0.4
            and risk_score < 0.7
            and action_str in ("strong-buy", "buy", "sell", "strong-sell")
        )

        # For buys, need positive 24h outlook
        if action_str in ("buy", "strong-buy") and higher_prob < 0.45:
            should_trade = False

        # Overbought dampens buys, encourages sells
        if overbought_prob >= 0.7:
            if action_str in ("buy", "strong-buy"):
                should_trade = False  # Don't buy into overbought conditions
            elif action_str in ("sell", "strong-sell"):
                should_trade = (
                    action_conf >= self.min_confidence
                    and risk_score < 0.7
                )  # Sell signals override genuine_demand when overbought

        # High pullback probability dampens buys
        if pullback_prob >= 0.7 and action_str in ("buy", "strong-buy"):
            should_trade = False

        result = {
            "asset": asset,
            "regime": regime_str,
            "regime_confidence": round(regime_conf, 3),
            "action": action_str,
            "action_confidence": round(action_conf, 3),
            "risk_level": round(risk_score, 3),
            "genuine_demand_prob": round(genuine_prob, 3),
            "higher_24h_prob": round(higher_prob, 3),
            "overbought_prob": round(overbought_prob, 3),
            "pullback_prob": round(pullback_prob, 3),
            "should_trade": should_trade,
            "timestamp": time.time(),
            "raw_answers": answers,
        }

        return result

    def _error_result(self, asset: str, error: str) -> dict:
        return {
            "asset": asset,
            "regime": "unknown",
            "regime_confidence": 0.0,
            "action": "hold",
            "action_confidence": 0.0,
            "risk_level": 1.0,
            "genuine_demand_prob": 0.0,
            "higher_24h_prob": 0.0,
            "overbought_prob": 0.0,
            "pullback_prob": 0.0,
            "should_trade": False,
            "error": error,
            "timestamp": time.time(),
            "raw_answers": [],
        }


class RiskManager:
    """Pure code risk management — no AI needed."""

    def __init__(
        self,
        max_usd_per_trade: float = 50,
        max_exposure_usd: float = 250,
        kelly_fraction: float = 0.25,
        daily_stop_loss: float = 50,
    ):
        self.max_usd_per_trade = max_usd_per_trade
        self.max_exposure_usd = max_exposure_usd
        self.kelly_fraction = kelly_fraction
        self.daily_stop_loss = daily_stop_loss
        self.open_positions = []
        self.daily_pnl = 0.0
        self.total_exposure = 0.0

    def check_trade(self, signal: dict, current_price: float) -> dict:
        """Check if a trade passes all risk gates."""
        checks = {
            "signal_should_trade": signal.get("should_trade", False),
            "confidence_ok": signal.get("action_confidence", 0) >= 0.7,
            "risk_ok": signal.get("risk_level", 1.0) < 0.7,
            "genuine_ok": signal.get("genuine_demand_prob", 0) >= 0.4,
            "exposure_ok": self.total_exposure < self.max_exposure_usd,
            "daily_loss_ok": self.daily_pnl > -self.daily_stop_loss,
            "not_duplicate": signal["asset"] not in [p["asset"] for p in self.open_positions],
        }

        all_pass = all(checks.values())

        # Calculate position size
        size_usd = 0
        if all_pass:
            # Simple Kelly-like sizing based on confidence
            conf = signal.get("action_confidence", 0)
            prob = signal.get("higher_24h_prob", 0.5)
            kelly = self._kelly(prob, 2.0)  # assume 2:1 reward/risk
            size_usd = min(
                self.max_usd_per_trade,
                self.max_exposure_usd - self.total_exposure,
                max(5, kelly * 100),  # min $5, scale by Kelly
            )

        return {
            "approved": all_pass,
            "checks": checks,
            "size_usd": round(size_usd, 2),
            "reason": self._reject_reason(checks),
        }

    def _kelly(self, prob: float, odds: float) -> float:
        """Fractional Kelly criterion."""
        if prob <= 0 or odds <= 0:
            return 0
        full_kelly = (prob * odds - (1 - prob)) / odds
        return max(0, full_kelly * self.kelly_fraction)

    def _reject_reason(self, checks: dict) -> str:
        failures = [k for k, v in checks.items() if not v]
        if not failures:
            return "approved"
        return f"rejected: {', '.join(failures)}"

    def record_fill(self, asset: str, side: str, size_usd: float, price: float):
        self.open_positions.append({
            "asset": asset, "side": side, "size_usd": size_usd,
            "price": price, "timestamp": time.time()
        })
        self.total_exposure += size_usd

    def record_close(self, asset: str, pnl: float):
        self.open_positions = [p for p in self.open_positions if p["asset"] != asset]
        self.total_exposure = sum(p["size_usd"] for p in self.open_positions)
        self.daily_pnl += pnl

    def reset_daily(self):
        self.daily_pnl = 0.0

    def calculate_trade_plan(self, signal: dict, current_price: float) -> dict:
        """
        Calculate concrete entry/SL/TP prices and position size for spot trading.

        Returns dict with: entry, sl, tp, risk_reward, position_size_usd
        """
        action = signal.get("action", "hold")
        risk_level = signal.get("risk_level", 0.5)
        conf = signal.get("action_confidence", 0.0)
        prob = signal.get("higher_24h_prob", 0.5)

        entry = current_price
        sl = entry
        tp = entry
        rr = 0.0
        size_usd = 0.0

        if action in ("buy", "strong-buy"):
            sl = entry * (1 - risk_level * 0.05)
            tp = entry * (1 + risk_level * 0.10)
            risk_dist = entry - sl
            reward_dist = tp - entry
            rr = reward_dist / risk_dist if risk_dist > 0 else 0.0
            kelly = self._kelly(prob, rr if rr > 0 else 2.0)
            size_usd = min(
                self.max_usd_per_trade,
                self.max_exposure_usd - self.total_exposure,
                max(5, kelly * 100),
            )
        elif action in ("sell", "strong-sell"):
            sl = entry * (1 + risk_level * 0.05)
            tp = entry * (1 - risk_level * 0.10)
            risk_dist = sl - entry
            reward_dist = entry - tp
            rr = reward_dist / risk_dist if risk_dist > 0 else 0.0
            kelly = self._kelly(1 - prob, rr if rr > 0 else 2.0)
            size_usd = min(
                self.max_usd_per_trade,
                self.max_exposure_usd - self.total_exposure,
                max(5, kelly * 100),
            )

        return {
            "entry": round(entry, 2),
            "sl": round(sl, 2),
            "tp": round(tp, 2),
            "risk_reward": round(rr, 2),
            "position_size_usd": round(size_usd, 2),
        }
