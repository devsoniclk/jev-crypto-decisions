#!/usr/bin/env python3
"""
Jev Crypto 5-Min Paper Trader — runs on5-minute cycles, paper trades, tracks P&L.
"""
import os
import sys
import time
import json
import signal as sig
from datetime import datetime, timedelta
from dotenv import load_dotenv

from scanner import MarketScanner, fetch_fear_greed_index
from jev_client import JevClient
from signals import SignalClassifier, RiskManager
from paper_trader import PaperTrader
from logger import DecisionLogger

load_dotenv()

# Config
INTERVAL_S = 300  # 5 minutes
ASSETS = ["BTC", "ETH", "SOL", "XRP"]
INITIAL_BALANCE = 10000
RUN_DURATION_S = 1800  # 30 minutes

# Kill switch
running = True
def handle_signal(signum, frame):
    global running
    running = False
    print("\n  [KILL] Stopping gracefully...")
sig.signal(sig.SIGINT, handle_signal)
sig.signal(sig.SIGTERM, handle_signal)


def get_api_key():
    key = os.getenv("OPENROUTER_API_KEY", "")
    if not key or key.startswith("sk-your"):
        print("ERROR: Set OPENROUTER_API_KEY in .env")
        sys.exit(1)
    return key


def print_header(cycle: int, start_time: float):
    elapsed = time.time() - start_time
    remaining = max(0, RUN_DURATION_S - elapsed)
    print(f"\n{'='*75}")
    print(f"  JEV CRYPTO 5M PAPER TRADER  |  Cycle {cycle}  |  {datetime.now().strftime('%H:%M:%S')}")
    print(f"  Elapsed: {int(elapsed)}s  |  Remaining: {int(remaining)}s  |  Interval: {INTERVAL_S}s")
    print(f"{'='*75}")


def print_market_data(scanner):
    data = scanner.scan()
    if not data:
        return []

    fng = fetch_fear_greed_index()
    fng_str = f"  Fear/Greed: {fng['value']} ({fng['label']})" if fng else ""

    print(f"\n  {'Asset':<6} {'Price':>12} {'1h':>8} {'24h':>8} {'7d':>8}")
    print(f"  {'-'*48}")
    for d in data:
        print(
            f"  {d['symbol']:<6} "
            f"${d['price']:>10,.2f} "
            f"{d['change_1h']:>+7.2f}% "
            f"{d['change_24h']:>+7.2f}% "
            f"{d['change_7d']:>+7.2f}%"
        )
    if fng_str:
        print(fng_str)
    return data


def run_decisions(scanner, classifier, risk, trader, logger):
    data = scanner.scan()
    if not data:
        return

    prices = {d["symbol"]: d["price"] for d in data}

    # Update existing positions (check TP/SL)
    closed = trader.update_positions(prices)
    for trade in closed:
        emoji = "+" if trade["pnl"] > 0 else ""
        print(f"\n  [CLOSED] {trade['asset']} {trade['side'].upper()} "
              f"Entry: ${trade['entry_price']:,.2f} -> Exit: ${trade['exit_price']:,.2f} "
              f"P&L: {emoji}${trade['pnl']:.2f} ({emoji}{trade['pnl_pct']:.2f}%) "
              f"Reason: {trade['exit_reason']}")

    # Run Jev decisions
    for d in data:
        asset = d["symbol"]

        # Skip if already have position
        if asset in trader.positions:
            continue

        state = scanner.get_state_string(d)
        sig_result = classifier.classify(state, asset)
        logger.log({**sig_result, "price_at_decision": d["price"]})

        if sig_result.get("should_trade"):
            risk_check = risk.check_trade(sig_result, d["price"])
            if risk_check["approved"]:
                size = risk_check["size_usd"]
                side = "buy" if sig_result["action"] in ("buy", "strong-buy") else "sell"
                opened = trader.open_position(asset, side, size, d["price"], sig_result)
                if opened:
                    print(f"\n  [OPENED] {asset} {side.upper()} ${size:.2f} @ ${d['price']:,.2f} "
                          f"(conf: {sig_result['action_confidence']:.1%}, regime: {sig_result['regime']})")
                    risk.record_fill(asset, side, size, d["price"])


def print_portfolio(trader, prices):
    # Open positions
    positions = trader.get_position_summary(prices)
    if positions:
        print(f"\n  OPEN POSITIONS:")
        print(f"  {'Asset':<6} {'Side':<5} {'Entry':>10} {'Current':>10} {'Size':>8} {'P&L':>10} {'P&L%':>8} {'Hold':>8}")
        print(f"  {'-'*70}")
        for p in positions:
            emoji = "+" if p["unrealized_pnl"] > 0 else ""
            hold_m = p["hold_seconds"] // 60
            print(
                f"  {p['asset']:<6} {p['side']:<5} "
                f"${p['entry']:>8,.2f} ${p['current']:>8,.2f} "
                f"${p['size_usd']:>6,.2f} "
                f"{emoji}${p['unrealized_pnl']:>8,.2f} {emoji}{p['unrealized_pct']:>6.2f}% "
                f"{hold_m:>5}m"
            )

    # Stats
    stats = trader.get_stats()
    print(f"\n  PORTFOLIO:")
    print(f"    Balance:      ${stats['balance']:,.2f}  (started: ${INITIAL_BALANCE:,.2f})")
    print(f"    Return:       {stats['return_pct']:+.2f}%")
    print(f"    Total P&L:    ${stats['total_pnl']:+.2f}")
    print(f"    Trades:       {stats['total_trades']}  (W:{stats['wins']} L:{stats['losses']})")
    print(f"    Win Rate:     {stats['win_rate']}")
    print(f"    Drawdown:     {stats['max_drawdown_pct']:.2f}%")
    if stats.get("best_trade"):
        bt = stats["best_trade"]
        print(f"    Best Trade:   {bt['asset']} ${bt['pnl']:+.2f} ({bt['pnl_pct']:+.2f}%)")
    if stats.get("worst_trade"):
        wt = stats["worst_trade"]
        print(f"    Worst Trade:  {wt['asset']} ${wt['pnl']:+.2f} ({wt['pnl_pct']:+.2f}%)")


def print_final_report(trader):
    stats = trader.get_stats()
    print(f"\n{'='*75}")
    print(f"  FINAL REPORT  |  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*75}")
    print(f"""
  Duration:         30 minutes ({len(trader.trades)} trades)
  Initial Balance:  ${INITIAL_BALANCE:,.2f}
  Final Balance:    ${stats['balance']:,.2f}
  Return:           {stats['return_pct']:+.2f}%
  Total P&L:        ${stats['total_pnl']:+.2f}
  
  Trades:           {stats['total_trades']}
  Wins:             {stats['wins']}
  Losses:           {stats['losses']}
  Win Rate:         {stats['win_rate']}
  Max Drawdown:     {stats['max_drawdown_pct']:.2f}%
""")

    if trader.trades:
        print(f"  TRADE HISTORY:")
        print(f"  {'#':<3} {'Asset':<6} {'Side':<5} {'Entry':>10} {'Exit':>10} {'P&L':>10} {'P&L%':>8} {'Hold':>6} {'Reason':<12} {'Exit Reason':<12}")
        print(f"  {'-'*90}")
        for i, t in enumerate(trader.trades):
            emoji = "+" if t["pnl"] > 0 else ""
            hold_m = t["held_seconds"] // 60
            exit_reason = t.get("exit_reason", "signal")
            print(
                f"  {i+1:<3} {t['asset']:<6} {t['side']:<5} "
                f"${t['entry_price']:>8,.2f} ${t['exit_price']:>8,.2f} "
                f"{emoji}${t['pnl']:>8,.2f} {emoji}{t['pnl_pct']:>6.2f}% "
                f"{hold_m:>4}m  {t['signal']['action']:<12} {exit_reason:<12}"
            )

    # Save report
    report_file = "data/paper_report.json"
    with open(report_file, "w") as f:
        json.dump({
            "stats": stats,
            "trades": trader.trades,
            "timestamp": datetime.now().isoformat(),
        }, f, indent=2)
    print(f"\n  Report saved to: {report_file}")


def main():
    global running

    key = get_api_key()
    scanner = MarketScanner(ASSETS)
    jev = JevClient(provider="openrouter", api_key=key)
    classifier = SignalClassifier(jev, min_confidence=0.65, min_edge=0.05)
    risk = RiskManager(max_usd_per_trade=500, max_exposure_usd=2000, kelly_fraction=0.25)
    trader = PaperTrader(initial_balance=INITIAL_BALANCE)
    logger = DecisionLogger()

    # Reset for fresh run
    trader.reset()
    print(f"\n  Starting Jev Crypto 5M Paper Trader")
    print(f"  Assets: {', '.join(ASSETS)}")
    print(f"  Balance: ${INITIAL_BALANCE:,.2f}")
    print(f"  Duration: {RUN_DURATION_S//60} minutes")
    print(f"  Interval: {INTERVAL_S} seconds")
    print(f"  TP: +3%  |  SL: -2%  |  Max hold: 30min")

    start_time = time.time()
    cycle = 0

    while running and (time.time() - start_time) < RUN_DURATION_S:
        cycle += 1
        print_header(cycle, start_time)

        # Print market data
        data = print_market_data(scanner)
        prices = {d["symbol"]: d["price"] for d in data} if data else {}

        # Run decisions
        run_decisions(scanner, classifier, risk, trader, logger)

        # Print portfolio
        print_portfolio(trader, prices)

        # Wait for next cycle
        elapsed = time.time() - start_time
        remaining = RUN_DURATION_S - elapsed
        if remaining > 0:
            wait = min(INTERVAL_S, remaining)
            print(f"\n  Next cycle in {int(wait)}s... (Ctrl+C to stop)")
            time.sleep(wait)

    # Close remaining positions at market
    data = scanner.scan()
    if data:
        prices = {d["symbol"]: d["price"] for d in data}
        for asset in list(trader.positions.keys()):
            if asset in prices:
                trade = trader.close_position(asset, prices[asset])
                trade["exit_reason"] = "run-end"
                print(f"  [CLOSED] {asset} @ ${prices[asset]:,.2f} P&L: ${trade['pnl']:+.2f}")

    # Final report
    print_final_report(trader)


if __name__ == "__main__":
    main()
