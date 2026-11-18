"""BTC race bot: slow EMA trend-following with a discount filter and a
two-stage trailing stop. Pure stdlib, deterministic, no network, no clock.

Strategy (one asset, CBBTC, long only, at most one open position, full size):

  Entry -- on a bar's close, when all of these hold:
    * EMA(20) is at least 15 bps above EMA(90) -- a slow, confirmed
      uptrend, not 1-minute noise (per-minute volatility is only ~7 bps);
    * the close is at least 100 bps below the highest close seen so far --
      we only buy a real trend off a discount, never near the highs, which
      keeps the bot in cash through range-bound chop;
    * the entry signal is armed (it disarms after every sell and re-arms
      only once the EMA gap has fallen back to zero or below, so a
      trailing-stop exit is never followed by an immediate rebuy, while a
      buy the market refuses is retried on the next bar -- and a refused
      buy leaves no stale state: the entry markers set when the order was
      sent are cleared as soon as the next batch shows no position).
  Exit -- the whole position, on the first of:
    * trailing stop: the close falls `TRAIL_BPS` (80 bps) below the highest
      close since entry -- wide enough to survive the 40-60 bps pullbacks
      inside a real rally;
    * once the position is up `ARM_GAIN_BPS` (80 bps) from its entry close,
      the trail tightens to `TRAIL_TIGHT_BPS` (30 bps), banking most of a
      rally instead of giving it back;
    * hard stop-loss: the position is worth 100 bps under its cost.

  Why this shape: the dev window falls 280 bps overall, so buy-and-hold
  loses ~$32 and fast EMA crosses churn away ~$130-180 in round-trip
  costs (~26 bps each). The window's one real move is a ~230 bps rally
  over ~3 hours; a slow EMA plus a wide-then-tight trail rides that rally
  in a single round trip and stays in cash the rest of the day.

  Orders cap their slippage at 100 bps (MAX_SLIPPAGE_BPS) past the close
  they were decided on, as the baselines do.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))

import makefun_bars

SYMBOL = "CBBTC"

FAST_SPAN = 20
SLOW_SPAN = 90
ENTER_GAP_BPS = 15          # EMA(20) must sit this far above EMA(90), in bps
DISCOUNT_BPS = 100          # close must sit this far below the running high
TRAIL_BPS = 80              # trailing stop while the trade is building
ARM_GAIN_BPS = 80           # unrealised gain at which the trail tightens
TRAIL_TIGHT_BPS = 30        # trailing stop once ARM_GAIN_BPS is reached
STOP_BPS = 100              # hard stop-loss vs cost, in bps
MAX_SLIPPAGE_BPS = 100


class Ema:
    """One EMA: seeded with the mean of its first `span` closes, then
    moving 2 / (span + 1) of the way to each new close (float64)."""

    __slots__ = ("span", "warm", "value")

    def __init__(self, span):
        self.span = span
        self.warm = []
        self.value = None

    def push(self, close):
        if self.value is not None:
            self.value += (2.0 / (self.span + 1)) * (close - self.value)
            return
        self.warm.append(close)
        if len(self.warm) == self.span:
            self.value = sum(self.warm) / self.span


class Bot:
    def __init__(self):
        self.fast = Ema(FAST_SPAN)
        self.slow = Ema(SLOW_SPAN)
        self.high = None        # highest close seen so far
        self.peak = None        # highest close since entry
        self.entry_close = None
        self.armed = True       # entry allowed (disarmed after each sell)
        self.awaiting_fill = False  # a buy was sent; not yet seen filled
        self.last_close = None

    def gap_bps(self):
        """EMA(20) minus EMA(90), in bps of the latest close; None until
        both EMAs are seeded."""
        if self.fast.value is None or self.slow.value is None:
            return None
        if self.last_close is None or self.last_close == 0:
            return None
        return (self.fast.value - self.slow.value) / self.last_close * 10000.0

    def on_batch(self, state, batch):
        for bar in batch["bars"]:
            if bar["symbol"] != SYMBOL:
                continue
            close = int(bar["c"])
            self.last_close = close
            if self.high is None or close > self.high:
                self.high = close
            self.fast.push(close)
            self.slow.push(close)

        if state.warming_up:
            return []

        held = state.positions.get(SYMBOL)
        gap = self.gap_bps()

        if self.awaiting_fill:
            # The buy sent on the previous bar has been answered: if no
            # position shows, it was refused -- drop the entry markers set
            # when the order was sent so a retry starts clean.
            if held is None:
                self.peak = None
                self.entry_close = None
            self.awaiting_fill = False

        if held is not None:
            # Track the peak and decide the exit on this close.
            if self.peak is None or self.last_close > self.peak:
                self.peak = self.last_close
            trail = TRAIL_BPS
            if self.entry_close is not None and self.last_close is not None:
                gain_bps = (self.last_close - self.entry_close) * 10000 // self.entry_close
                if gain_bps >= ARM_GAIN_BPS:
                    trail = TRAIL_TIGHT_BPS
            exit_now = False
            if self.peak is not None and self.last_close is not None:
                if self.last_close * 10000 <= self.peak * (10000 - trail):
                    exit_now = True
            if not exit_now:
                value = state.value(SYMBOL, held.qty)
                if value * 10000 <= held.cost * (10000 - STOP_BPS):
                    exit_now = True
            if exit_now:
                self.armed = False
                self.peak = None
                self.entry_close = None
                return [{"side": "sell", "symbol": SYMBOL, "qty": held.qty,
                         "max_slippage_bps": MAX_SLIPPAGE_BPS}]
            return []

        # Flat: re-arm once the trend has fully rolled over.
        if gap is not None and gap <= 0:
            self.armed = True

        if self.armed and gap is not None and gap > ENTER_GAP_BPS:
            if self.high is not None and self.last_close is not None:
                if self.last_close * 10000 <= self.high * (10000 - DISCOUNT_BPS):
                    room = state.weight_room(SYMBOL)
                    amount = state.cash
                    if room < amount:
                        amount = room
                    if amount >= int(state.hello["fees"]["min_notional_quote_units"]):
                        self.peak = self.last_close
                        self.entry_close = self.last_close
                        self.awaiting_fill = True
                        return [{"side": "buy", "symbol": SYMBOL,
                                 "notional_quote_units": amount,
                                 "max_slippage_bps": MAX_SLIPPAGE_BPS}]
        return []


makefun_bars.run(Bot().on_batch)
