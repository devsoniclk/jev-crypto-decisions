"""
Paper trading engine — tracks virtual positions, P&L, and win rate.
"""
import json
import os
import time
from datetime import datetime


class PaperTrader:
    """Paper trading engine with position tracking and P&L."""

    def __init__(self, initial_balance: float = 10000, state_file: str = "data/paper_state.json"):
        self.state_file = state_file
        self.initial_balance = initial_balance
        self._load_state()

    def _load_state(self):
        if os.path.exists(self.state_file):
            with open(self.state_file) as f:
                state = json.load(f)
            self.balance = state.get("balance", self.initial_balance)
            self.positions = state.get("positions", {})
            self.trades = state.get("trades", [])
            self.peak_balance = state.get("peak_balance", self.balance)
        else:
            self.balance = self.initial_balance
            self.positions = {}
            self.trades = []
            self.peak_balance = self.initial_balance

    def _save_state(self):
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        state = {
            "balance": self.balance,
            "positions": self.positions,
            "trades": self.trades,
            "peak_balance": self.peak_balance,
            "last_updated": datetime.now().isoformat(),
        }
        with open(self.state_file, "w") as f:
            json.dump(state, f, indent=2)

    def open_position(self, asset: str, side: str, size_usd: float, price: float, signal: dict):
        """Open a paper position."""
        if asset in self.positions:
            return False  # Already have a position

        qty = size_usd / price
        self.positions[asset] = {
            "side": side,
            "entry_price": price,
            "qty": qty,
            "size_usd": size_usd,
            "opened_at": time.time(),
            "signal": {
                "action": signal.get("action", ""),
                "confidence": signal.get("action_confidence", 0),
                "regime": signal.get("regime", ""),
                "risk_level": signal.get("risk_level", 0),
            },
        }
        self.balance -= size_usd
        self._save_state()
        return True

    def close_position(self, asset: str, current_price: float) -> dict:
        """Close a paper position and record the trade."""
        if asset not in self.positions:
            return {}

        pos = self.positions[asset]
        entry = pos["entry_price"]
        qty = pos["qty"]
        side = pos["side"]

        # Calculate P&L
        if side == "buy":
            pnl = (current_price - entry) * qty
            pnl_pct = (current_price - entry) / entry * 100
        else:  # sell/short
            pnl = (entry - current_price) * qty
            pnl_pct = (entry - current_price) / entry * 100

        # Record trade
        trade = {
            "asset": asset,
            "side": side,
            "entry_price": entry,
            "exit_price": current_price,
            "qty": qty,
            "size_usd": pos["size_usd"],
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "held_seconds": int(time.time() - pos["opened_at"]),
            "signal": pos["signal"],
            "closed_at": datetime.now().isoformat(),
        }
        self.trades.append(trade)

        # Update balance
        self.balance += pos["size_usd"] + pnl
        self.peak_balance = max(self.peak_balance, self.balance)

        # Remove position
        del self.positions[asset]
        self._save_state()
        return trade

    def update_positions(self, prices: dict) -> list:
        """Check positions against current prices. Close if take-profit or stop-loss hit."""
        closed = []
        for asset in list(self.positions.keys()):
            if asset not in prices:
                continue
            pos = self.positions[asset]
            current = prices[asset]
            entry = pos["entry_price"]
            side = pos["side"]

            if side == "buy":
                change_pct = (current - entry) / entry * 100
            else:
                change_pct = (entry - current) / entry * 100

            # Take profit at +3%
            if change_pct >= 3.0:
                trade = self.close_position(asset, current)
                trade["exit_reason"] = "take-profit"
                closed.append(trade)
            # Stop loss at -2%
            elif change_pct <= -2.0:
                trade = self.close_position(asset, current)
                trade["exit_reason"] = "stop-loss"
                closed.append(trade)
            # Time-based exit after 30 minutes
            elif time.time() - pos["opened_at"] > 1800:
                trade = self.close_position(asset, current)
                trade["exit_reason"] = "time-exit"
                closed.append(trade)

        return closed

    def get_stats(self) -> dict:
        """Calculate trading statistics."""
        if not self.trades:
            return {
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": "0%",
                "total_pnl": 0,
                "balance": self.balance,
                "return_pct": 0,
                "open_positions": len(self.positions),
                "max_drawdown": 0,
            }

        wins = [t for t in self.trades if t["pnl"] > 0]
        losses = [t for t in self.trades if t["pnl"] <= 0]
        total_pnl = sum(t["pnl"] for t in self.trades)
        total_pnl_pct = sum(t["pnl_pct"] for t in self.trades)

        # Drawdown
        drawdown = (self.peak_balance - self.balance) / self.peak_balance * 100 if self.peak_balance > 0 else 0

        # Best/worst trades
        best = max(self.trades, key=lambda t: t["pnl"]) if self.trades else None
        worst = min(self.trades, key=lambda t: t["pnl"]) if self.trades else None

        # Avg hold time
        avg_hold = sum(t["held_seconds"] for t in self.trades) / len(self.trades) if self.trades else 0

        return {
            "total_trades": len(self.trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": f"{len(wins)/len(self.trades)*100:.1f}%",
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": round(total_pnl_pct, 2),
            "balance": round(self.balance, 2),
            "return_pct": round((self.balance - self.initial_balance) / self.initial_balance * 100, 2),
            "open_positions": len(self.positions),
            "max_drawdown_pct": round(drawdown, 2),
            "avg_hold_seconds": int(avg_hold),
            "best_trade": best,
            "worst_trade": worst,
        }

    def get_position_summary(self, current_prices: dict) -> list:
        """Get summary of open positions with unrealized P&L."""
        summary = []
        for asset, pos in self.positions.items():
            if asset not in current_prices:
                continue
            current = current_prices[asset]
            entry = pos["entry_price"]
            side = pos["side"]

            if side == "buy":
                unrealized = (current - entry) * pos["qty"]
                unrealized_pct = (current - entry) / entry * 100
            else:
                unrealized = (entry - current) * pos["qty"]
                unrealized_pct = (entry - current) / entry * 100

            summary.append({
                "asset": asset,
                "side": side,
                "entry": entry,
                "current": current,
                "size_usd": pos["size_usd"],
                "unrealized_pnl": round(unrealized, 2),
                "unrealized_pct": round(unrealized_pct, 2),
                "hold_seconds": int(time.time() - pos["opened_at"]),
            })
        return summary

    def reset(self):
        """Reset paper trading state."""
        self.balance = self.initial_balance
        self.positions = {}
        self.trades = []
        self.peak_balance = self.initial_balance
        self._save_state()
