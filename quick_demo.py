#!/usr/bin/env python3
"""Quick 10-cycle paper trading demo."""
import os, sys, time, json
from datetime import datetime

# Ensure we're in the right directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, '.')

from dotenv import load_dotenv
load_dotenv()

from scanner import MarketScanner
from jev_client import JevClient
from signals import SignalClassifier, RiskManager
from paper_trader import PaperTrader

key = os.getenv('OPENROUTER_API_KEY')
scanner = MarketScanner(['BTC', 'ETH', 'SOL', 'XRP'])
jev = JevClient(provider='openrouter', api_key=key)
classifier = SignalClassifier(jev, min_confidence=0.50, min_edge=0.02)
risk = RiskManager(max_usd_per_trade=1000, max_exposure_usd=4000, kelly_fraction=0.35)
trader = PaperTrader(initial_balance=10000, state_file='data/paper_state.json')
trader.reset()

print(f"Jev 5M Paper Trader | Balance: $10,000 | 10 cycles @ 30s")
print(f"TP: +2% | SL: -1.5% | Conf: >=0.50 | Edge: >=0.02")
print()

for cycle in range(10):
    data = scanner.scan()
    prices = {d['symbol']: d['price'] for d in data}

    # Check TP/SL
    for asset in list(trader.positions.keys()):
        if asset in prices:
            pos = trader.positions[asset]
            entry = pos['entry_price']
            curr = prices[asset]
            chg = (curr - entry) / entry * 100 if pos['side'] == 'buy' else (entry - curr) / entry * 100
            if chg >= 2.0:
                t = trader.close_position(asset, curr)
                t['exit_reason'] = 'take-profit'
                print(f"  [TP] {asset} ${t['pnl']:+.2f} ({chg:+.1f}%)")
            elif chg <= -1.5:
                t = trader.close_position(asset, curr)
                t['exit_reason'] = 'stop-loss'
                print(f"  [SL] {asset} ${t['pnl']:+.2f} ({chg:+.1f}%)")
            elif (time.time() - pos['opened_at']) > 600:
                t = trader.close_position(asset, curr)
                t['exit_reason'] = 'time-exit'
                print(f"  [TIME] {asset} ${t['pnl']:+.2f} ({chg:+.1f}%)")

    # Jev decisions
    for d in data:
        asset = d['symbol']
        if asset in trader.positions:
            continue
        state = scanner.get_state_string(d)
        sig = classifier.classify(state, asset)
        action = sig.get('action', 'hold')
        conf = sig.get('action_confidence', 0)
        should = sig.get('should_trade', False)

        icon = {'buy': 'BUY', 'strong-buy': 'BUY', 'sell': 'SELL', 'strong-sell': 'SELL'}.get(action, '---')
        print(f"  {cycle+1}. {asset} @ ${d['price']:>10,.2f} | {icon} conf={conf:.0%} regime={sig.get('regime','?')} genuine={sig.get('genuine_demand_prob',0):.0%} | trade={should}")

        if should:
            rc = risk.check_trade(sig, d['price'])
            if rc['approved']:
                side = 'buy' if action in ('buy', 'strong-buy') else 'sell'
                ok = trader.open_position(asset, side, rc['size_usd'], d['price'], sig)
                if ok:
                    print(f"     >>> OPENED {asset} {side.upper()} ${rc['size_usd']:.2f} @ ${d['price']:,.2f}")

    # Portfolio
    stats = trader.get_stats()
    pos = trader.get_position_summary(prices)
    for p in pos:
        e = '+' if p['unrealized_pnl'] > 0 else ''
        print(f"     POS: {p['asset']} entry=${p['entry']:,.2f} now=${p['current']:,.2f} P&L={e}${p['unrealized_pnl']:.2f} ({e}{p['unrealized_pct']:.1f}%)")
    print(f"     Balance: ${stats['balance']:,.2f} | Trades: {stats['total_trades']} | P&L: ${stats['total_pnl']:+.2f}")
    print()

    if cycle < 9:
        time.sleep(30)

# Close all
data = scanner.scan()
prices = {d['symbol']: d['price'] for d in data}
for asset in list(trader.positions.keys()):
    if asset in prices:
        t = trader.close_position(asset, prices[asset])
        t['exit_reason'] = 'run-end'
        print(f"  [END] {asset} ${t['pnl']:+.2f}")

# Report
stats = trader.get_stats()
print(f"\n{'='*65}")
print(f"  FINAL REPORT  |  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"{'='*65}")
print(f"  Balance:    ${stats['balance']:,.2f} (started $10,000)")
print(f"  Return:     {stats['return_pct']:+.2f}%")
print(f"  P&L:        ${stats['total_pnl']:+.2f}")
print(f"  Trades:     {stats['total_trades']} (W:{stats['wins']} L:{stats['losses']})")
print(f"  Win Rate:   {stats['win_rate']}")
print(f"  Drawdown:   {stats['max_drawdown_pct']:.2f}%")
print(f"  Jev Calls:  {jev.stats()['total_calls']}")
print(f"  Jev Cost:   ${jev.stats()['total_cost_usd']:.6f}")

if trader.trades:
    print(f"\n  TRADES:")
    for i, t in enumerate(trader.trades):
        e = '+' if t['pnl'] > 0 else ''
        print(f"    {i+1}. {t['asset']} {t['side']} ${t['entry_price']:,.2f}->${t['exit_price']:,.2f} P&L={e}${t['pnl']:.2f} ({e}{t['pnl_pct']:.1f}%) {t.get('exit_reason','')}")

# Save
with open('data/paper_report.json', 'w') as f:
    json.dump({'stats': stats, 'trades': trader.trades, 'jev_cost': jev.stats()}, f, indent=2)
print(f"\n  Report saved to data/paper_report.json")
