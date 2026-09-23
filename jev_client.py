"""
Jev client for TypeSafe's System One model.
Supports direct TypeSafe API and OpenRouter /api/alpha/decisions endpoint.
"""
import json
import time
import requests
from typing import Any


class JevClient:
    """Calls Jev via TypeSafe API or OpenRouter."""

    def __init__(self, provider: str, api_key: str, model: str = "typesafe/jev-1.13", timeout: int = 30):
        self.provider = provider
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.total_cost = 0.0
        self.total_calls = 0
        self.total_tokens = 0

    def decide(self, state: str, questions: list[dict]) -> list[dict]:
        """
        Send a typed decision request to Jev.

        Args:
            state: The context/information string
            questions: List of question dicts with keys:
                - type: "choice" | "score" | "noul"
                - instructions: The question text
                - options: (for choice/score) list of option strings

        Returns:
            List of answer dicts with probabilities
        """
        start = time.time()
        if self.provider == "typesafe":
            results, usage = self._call_typesafe(state, questions)
        elif self.provider == "openrouter":
            results, usage = self._call_openrouter(state, questions)
        else:
            raise ValueError(f"Unknown provider: {self.provider}")

        elapsed = time.time() - start
        self.total_calls += 1
        self.total_cost += usage.get("cost", 0.00002)
        self.total_tokens += usage.get("input_tokens", 0)
        return results

    def _call_typesafe(self, state: str, questions: list[dict]) -> tuple:
        """Call TypeSafe's System One API directly."""
        url = "https://api.typesafe.ai/v1/systemone"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        q_payload = {}
        for i, q in enumerate(questions):
            key = f"q{i}"
            q_def = {"type": q["type"], "instructions": q["instructions"]}
            if "options" in q:
                q_def["criteria"] = {opt: opt for opt in q["options"]}
            q_payload[key] = q_def

        payload = {"state": state, "questions": q_payload}
        resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()

        results = []
        for i, q in enumerate(questions):
            key = f"q{i}"
            answer = data.get("answers", {}).get(key, {})
            results.append(self._normalize_answer(answer, q))

        usage = data.get("usage", {})
        return results, usage

    def _call_openrouter(self, state: str, questions: list[dict]) -> tuple:
        """Call Jev via OpenRouter's /api/alpha/decisions endpoint."""
        url = "https://openrouter.ai/api/alpha/decisions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Build questions in Jev format
        q_payload = {}
        for i, q in enumerate(questions):
            key = f"q{i}"
            q_def = {"type": q["type"], "instructions": q["instructions"]}
            if "options" in q:
                if q["type"] == "score":
                    # Score expects criteria as a list
                    q_def["criteria"] = q["options"]
                else:
                    # Choice expects criteria as {option: description}
                    q_def["criteria"] = {opt: opt for opt in q["options"]}
            q_payload[key] = q_def

        payload = {
            "model": self.model,
            "state": state,
            "questions": q_payload,
        }

        resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()

        # Parse answers
        results = []
        answers = data.get("answers", {})
        for i, q in enumerate(questions):
            key = f"q{i}"
            answer = answers.get(key, {})
            results.append(self._normalize_answer(answer, q))

        usage = data.get("usage", {})
        return results, usage

    def _normalize_answer(self, answer: dict, question: dict) -> dict:
        """Normalize response to standard format."""
        q_type = question["type"]
        if q_type == "choice":
            return {
                "type": "choice",
                "choice": answer.get("choice", ""),
                "probabilities": answer.get("probabilities", {}),
                "confidence": answer.get("confidence", 0.0),
            }
        elif q_type == "noul":
            return {
                "type": "noul",
                "noul": answer.get("noul", 0.5),
            }
        elif q_type == "score":
            return {
                "type": "score",
                "score": answer.get("score", 0.0),
                "probabilities": answer.get("probabilities", {}),
                "confidence": answer.get("confidence", 0.0),
            }
        return answer

    def stats(self) -> dict:
        return {
            "total_calls": self.total_calls,
            "total_cost_usd": round(self.total_cost, 6),
            "total_tokens": self.total_tokens,
            "provider": self.provider,
            "model": self.model,
        }
