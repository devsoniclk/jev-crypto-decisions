"""
Market scanner — fetches live crypto data from CoinGecko (free, no API key).
Provides price, volume, market cap, 24h change for Jev state construction.
"""
import time
import requests
from typing import Optional


COINGECKO_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "XRP": "ripple",
    "DOGE": "dogecoin",
    "ADA": "cardano",
    "AVAX": "avalanche-2",
    "DOT": "polkadot",
    "LINK": "chainlink",
    "MATIC": "matic-network",
}


class MarketScanner:
    """Fetches live crypto market data from CoinGecko."""

    BASE = "https://api.coingecko.com/api/v3"

    def __init__(self, assets: list[str], source: str = "coingecko"):
        self.assets = [a.upper() for a in assets]
        self.source = source
        self._cache = {}
        self._cache_ts = 0

    def scan(self, max_age_s: int = 60) -> list[dict]:
        """Fetch current market data for all assets. Caches for max_age_s."""
        now = time.time()
        if self._cache and (now - self._cache_ts) < max_age_s:
            return list(self._cache.values())

        ids = [COINGECKO_IDS[a] for a in self.assets if a in COINGECKO_IDS]
        if not ids:
            return []

        try:
            resp = requests.get(
                f"{self.BASE}/coins/markets",
                params={
                    "vs_currency": "usd",
                    "ids": ",".join(ids),
                    "order": "market_cap_desc",
                    "sparkline": "false",
                    "price_change_percentage": "1h,24h,7d",
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"[scanner] CoinGecko error: {e}")
            return list(self._cache.values()) if self._cache else []

        results = []
        for coin in data:
            symbol = coin["symbol"].upper()
            entry = {
                "symbol": symbol,
                "name": coin["name"],
                "price": coin["current_price"],
                "market_cap": coin["market_cap"],
                "volume_24h": coin["total_volume"],
                "change_1h": coin.get("price_change_percentage_1h_in_currency", 0) or 0,
                "change_24h": coin.get("price_change_percentage_24h_in_currency", 0) or 0,
                "change_7d": coin.get("price_change_percentage_7d_in_currency", 0) or 0,
                "high_24h": coin["high_24h"],
                "low_24h": coin["low_24h"],
                "ath": coin["ath"],
                "ath_change_pct": coin["ath_change_percentage"],
                "timestamp": time.time(),
            }
            results.append(entry)
            self._cache[symbol] = entry

        self._cache_ts = now
        return results

    def get_state_string(self, asset_data: dict) -> str:
        """Build a state string for Jev from market data."""
        d = asset_data
        vol_m = d["volume_24h"] / 1_000_000
        mcap_b = d["market_cap"] / 1_000_000_000

        state = (
            f"Asset: {d['symbol']} ({d['name']})\n"
            f"Price: ${d['price']:,.2f}\n"
            f"Market Cap: ${mcap_b:,.1f}B\n"
            f"24h Volume: ${vol_m:,.0f}M\n"
            f"1h Change: {d['change_1h']:+.2f}%\n"
            f"24h Change: {d['change_24h']:+.2f}%\n"
            f"7d Change: {d['change_7d']:+.2f}%\n"
            f"24h High: ${d['high_24h']:,.2f}\n"
            f"24h Low: ${d['low_24h']:,.2f}\n"
            f"ATH: ${d['ath']:,.2f} ({d['ath_change_pct']:+.1f}% from ATH)\n"
        )
        return state


def fetch_fear_greed_index() -> Optional[dict]:
    """Fetch the Crypto Fear & Greed Index."""
    try:
        resp = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
        resp.raise_for_status()
        data = resp.json()["data"][0]
        return {
            "value": int(data["value"]),
            "label": data["value_classification"],
        }
    except Exception:
        return None
