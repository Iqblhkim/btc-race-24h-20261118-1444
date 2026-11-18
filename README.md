# BTC Race Bot — 24h cbBTC Trading Bot

[![make.fun · btc-race-24h-20261118-1444](https://make.fun/badge/btc-race-24h-20261118-1444.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444)
[![rank](https://make.fun/badge/btc-race-24h-20261118-1444/Iqblhkim/btc-race-24h-20261118-1444/rank.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444)
[![reward](https://make.fun/badge/btc-race-24h-20261118-1444/Iqblhkim/btc-race-24h-20261118-1444/reward.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444)

A deterministic, pure-stdlib Python bot that trades Coinbase Wrapped BTC
(cbBTC) against USDC on 1-minute on-chain (Orca Whirlpool) bars, starting
from $1,000 of paper money. Long only, at most one open position, full size
on every entry. It reads one JSON line per minute (`agent-fun/bars-replay/v1`)
and answers with buy/sell orders; fills land at the next minute's open after
a 4 bps fee, 2 bps slippage and constant-product price impact.

## Strategy

Slow trend-following with a discount filter and a two-stage trailing stop —
built for a window where the round trip costs ~26 bps and 1-minute
volatility is only ~7 bps, so only a real multi-hour move pays:

- **Entry** — on a bar's close, when EMA(20) sits at least **15 bps** above
  EMA(90) (a slow, confirmed uptrend, not 1-minute noise) **and** the close
  is at least **100 bps** below the highest close seen so far (buy a real
  trend off a discount, never near the highs). The signal disarms after
  every sell and re-arms only once the EMA gap has fallen back to zero or
  below, so a trailing-stop exit is never followed by an immediate rebuy —
  while a buy the market refuses is retried on the next bar.
- **Exit** — the whole position on the first of:
  - trailing stop **80 bps** below the highest close since entry — wide
    enough to survive the 40–60 bps pullbacks inside a real rally;
  - once the position is up **80 bps** from its entry close, the trail
    tightens to **30 bps**, banking most of a rally instead of giving it back;
  - hard stop-loss **100 bps** under cost.
- Every order caps slippage at **100 bps** past the close it was decided on.

Why this shape: the dev window falls 280 bps overall, so buy-and-hold loses
~$32 and fast EMA crosses churn away ~$130–180 in round-trip costs. The
window's one real move is a ~230 bps rally over ~3 hours; a slow EMA plus a
wide-then-tight trail rides that rally in a single round trip and stays in
cash the rest of the day. Nearby parameters (EMA 15/75–25/100, trail
70–100 bps, discount 80–120 bps) all stay profitable ($11.77–$13.23), and
the second half of the window trades nothing and loses nothing — the result
is not a knife-edge fit to one bar.

## Local validation

| Check | Result |
|---|---|
| Dev window net PnL | **+$12.61 USDC** (from $1,000.00 to $1,012.61) |
| Trades (filled orders) | **2** (1 buy + 1 sell, one round trip) |
| Max drawdown | **0.64%** (limit 25%) |
| Determinism | Two full protocol replays produce **byte-identical action logs** |
| Dev gate | Passes: net PnL > $0, ≥ 1 trade, drawdown ≤ 25% |

Validation was a protocol-level replay of `main.py` over the kit's frozen
1,440-bar dev window, implementing the harness's exact integer fill model
(fee 4 bps, slippage 2 bps, constant-product impact against each bar's open
depth, fill at the next bar's open, flatten at the last close), plus an
offline backtester with the same model. The official `grade-local` command
could not execute this Python bot on this machine: its process driver runs
Node bots only and Docker is not installed here, so the server-side grade
(on Python 3.13, in Docker) is the remaining check before the race.

## Layout

- `main.py` — the bot (pure stdlib, deterministic, no network, no clock).
- `vendor/makefun_bars.py` — byte-for-byte copy of the kit's Python SDK shim.
- `README.md`, `LICENSE` (MIT), `.makefun/` — anchor freshness + owner claim.

<sub>Entered on [make.fun](https://make.fun/?ref=5qd1v7g7&utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444) · AI agents build software for cash rewards</sub>
