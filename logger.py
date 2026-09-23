"""
Decision logger — appends every Jev decision to JSONL for audit/backtest.
"""
import json
import os
import time


class DecisionLogger:
    """Append-only JSONL logger for all Jev decisions."""

    def __init__(self, log_path: str = "data/decisions.jsonl"):
        self.log_path = log_path
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

    def log(self, decision: dict):
        """Append a decision to the log."""
        entry = {
            **decision,
            "logged_at": time.time(),
        }
        with open(self.log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")

    def read_all(self) -> list[dict]:
        """Read all logged decisions."""
        if not os.path.exists(self.log_path):
            return []
        decisions = []
        with open(self.log_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        decisions.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return decisions

    def stats(self) -> dict:
        """Summary stats from logged decisions."""
        decisions = self.read_all()
        if not decisions:
            return {"total": 0}

        trades = [d for d in decisions if d.get("should_trade")]
        actions = {}
        for d in decisions:
            act = d.get("action", "unknown")
            actions[act] = actions.get(act, 0) + 1

        return {
            "total_decisions": len(decisions),
            "trade_signals": len(trades),
            "trade_rate": f"{len(trades)/len(decisions)*100:.1f}%",
            "action_breakdown": actions,
            "assets_seen": list(set(d.get("asset", "") for d in decisions)),
        }
