# Jev Crypto Decisions

**Jev-powered crypto trading signal system.** Uses TypeSafe AI's System One model for calibrated, typed decisions at $0.00006 per call.

## What It Does

1. **Scans** live crypto market data (CoinGecko, free)
2. **Classifies** each asset via Jev typed decisions (regime, action, risk)
3. **Gates** trades through pure-code risk management (Kelly sizing, exposure limits)
4. **Logs** every decision to JSONL for audit/backtest
5. **Runs** as a continuous loop or one-shot

## Quick Start

```bash
cd ~/Projects/jev-crypto-decisions
cp .env.example .env
# Edit .env — add your OPENROUTER_API_KEY or TYPESAFE_API_KEY

source .venv/bin/activate

# Test the connection
python run.py test

# Scan markets (no API key needed)
python run.py scan

# Run Jev decisions on all assets
python run.py decide

# Continuous loop (every 5 min)
python run.py run --interval 300

# View logged statistics
python run.py stats
```

## Architecture

```
CoinGecko API  -->  Market Scanner  -->  State String
                                            |
                                      Jev (28ms)
                                            |
                                      Typed Decisions
                                      (regime, action, risk, genuine, 24h outlook)
                                            |
                                      Risk Manager
                                      (Kelly, exposure, stop-loss, duplicates)
                                            |
                                      Decision Logger (JSONL)
```

## Jev Questions Per Asset

| # | Type | Question | Returns |
|---|------|----------|---------|
| 1 | Choice | Market regime? | trending-up/down/ranging/breakout/breakdown |
| 2 | Choice | Trading action? | strong-buy/buy/hold/sell/strong-sell |
| 3 | Score | Risk level? | very-low to extreme (0-4) |
| 4 | Noul | Genuine demand? | P(yes) — not manipulation/spike |
| 5 | Noul | Higher in 24h? | P(yes) — directional outlook |

## Cost

- **Per scan (4 assets):** ~$0.00024 (4 × $0.00006)
- **Per hour (12 scans):** ~$0.003
- **Per day (288 scans):** ~$0.07
- **Per month:** ~$2.16

Compare to GPT-4: ~$50–500/day for the same workload.

## Risk Management

- Max $50 per trade
- Max $250 total exposure
- 0.25 Kelly fraction
- $50 daily stop loss
- No duplicate positions
- Kill switch: `touch data/KILL`

## Files

```
run.py          CLI & runner
jev_client.py   Jev API client (TypeSafe + OpenRouter)
scanner.py      CoinGecko market data fetcher
signals.py      Signal classifier + risk manager
logger.py       JSONL decision logger
config.yaml     Configuration
data/           Decision logs, kill switch
```

## License

MIT
