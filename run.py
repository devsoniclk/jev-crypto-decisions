#!/usr/bin/env python3
"""
Jev Crypto Decisions — CLI & Runner

Commands:
    scan        Scan markets and show current data
    decide      Run Jev decisions on all assets (one-shot)
    run         Continuous scanning loop
    stats       Show logged decision statistics
    test        Test Jev connection with a simple question
    backtest    (coming soon)

Usage:
    python run.py scan
    python run.py decide
    python run.py run --interval 300
    python run.py test
    python run.py stats
"""
import os
import sys
import time
import yaml
import argparse
from datetime import datetime
from dotenv import load_dotenv

from scanner import MarketScanner, fetch_fear_greed_index
from jev_client import JevClient
from signals import SignalClassifier, RiskManager
from logger import DecisionLogger


def load_config():
    load_dotenv()
    with open("config.yaml") as f:
        cfg = yaml.safe_load(f)
    return cfg


def get_api_key(cfg):
    """Get API key from env based on configured provider."""
    provider = cfg["jev"]["provider"]
    if provider == "typesafe":
        key = os.getenv("TYPESAFE_API_KEY", "")
    elif provider == "openrouter":
        key = os.getenv("OPENROUTER_API_KEY", "")
    else:
        key = ""
    if not key or key.startswith("sk-your"):
        print(f"ERROR: Set {'TYPESAFE_API_KEY' if provider == 'typesafe' else 'OPENROUTER_API_KEY'} in .env")
        sys.exit(1)
    return key


def cmd_scan(cfg):
    """Scan markets and display current data."""
    scanner = MarketScanner(cfg["scanner"]["assets"])
    print("\n" + "=" * 70)
    print(f"  MARKET SCAN  |  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    data = scanner.scan()
    if not data:
        print("  No data available. Check connection.")
        return

    fng = fetch_fear_greed_index()

    print(f"\n  {'Asset':<6} {'Price':>12} {'1h':>8} {'24h':>8} {'7d':>8} {'Vol 24h':>12}")
    print("  " + "-" * 60)
    for d in data:
        print(
            f"  {d['symbol']:<6} "
            f"${d['price']:>10,.2f} "
            f"{d['change_1h']:>+7.2f}% "
            f"{d['change_24h']:>+7.2f}% "
            f"{d['change_7d']:>+7.2f}% "
            f"${d['volume_24h']/1e6:>9,.0f}M"
        )

    if fng:
        print(f"\n  Fear & Greed Index: {fng['value']} ({fng['label']})")
    print()


def cmd_decide(cfg):
    """Run Jev decisions on all assets."""
    key = get_api_key(cfg)
    scanner = MarketScanner(cfg["scanner"]["assets"])
    jev = JevClient(
        provider=cfg["jev"]["provider"],
        api_key=key,
        model=cfg["jev"]["model"],
    )
    classifier = SignalClassifier(
        jev, min_confidence=cfg["signal"]["min_confidence"],
        min_edge=cfg["signal"]["min_edge"],
    )
    risk = RiskManager(
        max_usd_per_trade=cfg["risk"]["max_usd_per_trade"],
        max_exposure_usd=cfg["risk"]["max_exposure_usd"],
        kelly_fraction=cfg["risk"]["kelly_fraction"],
    )
    log = DecisionLogger(cfg["logging"]["decisions_log"])

    data = scanner.scan()
    if not data:
        print("No market data available.")
        return

    print("\n" + "=" * 70)
    print(f"  JEV DECISIONS  |  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    for d in data:
        state = scanner.get_state_string(d)
        sig = classifier.classify(state, d["symbol"])

        # Log it
        log.log({**sig, "price_at_decision": d["price"], "market_data": d})

        # Risk check
        risk_check = risk.check_trade(sig, d["price"])

        # Display
        action = sig["action"].upper()
        conf = sig["action_confidence"]
        regime = sig["regime"]
        risk_lvl = sig["risk_level"]
        genuine = sig["genuine_demand_prob"]
        higher = sig["higher_24h_prob"]
        trade = "YES" if risk_check["approved"] else "NO"

        # Color-coded action
        action_display = action
        if action in ("STRONG-BUY", "BUY"):
            action_display = f"[BUY]  {action}"
        elif action in ("STRONG-SELL", "SELL"):
            action_display = f"[SELL] {action}"
        else:
            action_display = f"[---]  {action}"

        print(f"\n  {d['symbol']} @ ${d['price']:,.2f}")
        print(f"    Action:    {action_display}  (conf: {conf:.1%})")
        print(f"    Regime:    {regime}")
        print(f"    Risk:      {risk_lvl:.1%}")
        print(f"    Genuine:   {genuine:.1%}  |  24h outlook: {higher:.1%}")
        print(f"    Trade?     {trade}  |  Size: ${risk_check['size_usd']:.2f}")
        if not risk_check["approved"]:
            print(f"    Reason:    {risk_check['reason']}")

    print(f"\n  Jev Stats: {jev.stats()['total_calls']} calls, ${jev.stats()['total_cost_usd']:.6f}")
    print()


def cmd_test(cfg):
    """Test Jev connection with a simple question."""
    key = get_api_key(cfg)
    jev = JevClient(
        provider=cfg["jev"]["provider"],
        api_key=key,
        model=cfg["jev"]["model"],
    )

    print(f"\nTesting Jev connection ({cfg['jev']['provider']} / {cfg['jev']['model']})...")

    state = (
        "Asset: BTC (Bitcoin)\n"
        "Price: $67,432\n"
        "24h Change: +4.2%\n"
        "Volume: $28B\n"
        "Fear/Greed: 72 (Greed)\n"
        "Funding rate: +0.03%\n"
    )

    questions = [
        {
            "type": "choice",
            "instructions": "What is the market regime for BTC?",
            "options": ["trending-up", "trending-down", "ranging", "breakout", "breakdown"],
        },
        {
            "type": "noul",
            "instructions": "BTC is likely to be higher in 24 hours.",
        },
    ]

    try:
        answers = jev.decide(state, questions)
        print("\n  SUCCESS! Jev responded:")
        for i, (q, a) in enumerate(zip(questions, answers)):
            print(f"\n  Q{i}: {q['instructions']}")
            print(f"  A{i}: {a}")
        print(f"\n  Cost: ${jev.stats()['total_cost_usd']:.6f}")
        print(f"  Latency: ~{jev.stats()['total_calls']} call(s)")
    except Exception as e:
        print(f"\n  FAILED: {e}")
        print("\n  Check your API key in .env and network connection.")


def cmd_stats(cfg):
    """Show logged decision statistics."""
    log = DecisionLogger(cfg["logging"]["decisions_log"])
    stats = log.stats()

    print("\n" + "=" * 70)
    print("  DECISION STATISTICS")
    print("=" * 70)

    if stats.get("total_decisions", 0) == 0:
        print("\n  No decisions logged yet. Run 'python run.py decide' first.\n")
        return

    print(f"\n  Total decisions:  {stats['total_decisions']}")
    print(f"  Trade signals:    {stats['trade_signals']} ({stats['trade_rate']})")
    print(f"  Assets covered:   {', '.join(stats['assets_seen'])}")
    print(f"\n  Action breakdown:")
    for action, count in stats["action_breakdown"].items():
        pct = count / stats["total_decisions"] * 100
        print(f"    {action:<15} {count:>5}  ({pct:.1f}%)")
    print()


def cmd_run(cfg, interval: int = 300):
    """Continuous scanning loop."""
    print(f"\nStarting continuous scan (interval: {interval}s)")
    print("Press Ctrl+C to stop.\n")

    while True:
        try:
            cmd_decide(cfg)
            print(f"  Next scan in {interval}s...")
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\nStopped.")
            break


def main():
    parser = argparse.ArgumentParser(description="Jev Crypto Decisions")
    parser.add_argument("command", choices=["scan", "decide", "run", "stats", "test"],
                        help="Command to run")
    parser.add_argument("--interval", type=int, default=300,
                        help="Scan interval in seconds (for 'run' command)")
    args = parser.parse_args()

    cfg = load_config()

    if args.command == "scan":
        cmd_scan(cfg)
    elif args.command == "decide":
        cmd_decide(cfg)
    elif args.command == "run":
        cmd_run(cfg, args.interval)
    elif args.command == "stats":
        cmd_stats(cfg)
    elif args.command == "test":
        cmd_test(cfg)


if __name__ == "__main__":
    main()
