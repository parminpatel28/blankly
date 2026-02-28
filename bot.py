import numpy as np
import blankly
from datetime import datetime
import pytz

# UME Rule Strategy - Refined for SPY
SYMBOLS = ['SPY']


def price_event(price, symbol, state: blankly.StrategyState):
    """
    Refined UME Strategy with fixed precision handling.
    """
    # Fetch 100 bars to calculate Moving Averages
    bars_df = state.interface.history(
        symbol, to=100, return_as='df', resolution='15m')

    if len(bars_df) < 21:
        return

    # === INITIALIZE STATE VARIABLES ===
    if not hasattr(state.variables, 'high_water_mark'):
        state.variables.high_water_mark = 0
        state.variables.entry_price = 0

    # === TIME & DATE CHECK ===
    eastern = pytz.timezone('US/Eastern')
    current_time = datetime.fromtimestamp(
        bars_df.index[-1] / 1000 if bars_df.index[-1] > 1e12 else bars_df.index[-1], tz=eastern)

    # 10:15 AM to 3:45 PM EST Trading Window
    if current_time.hour < 10 or (current_time.hour == 10 and current_time.minute < 15):
        return

    actual_position = state.interface.account[state.base_asset].available

    # Market Close Logic: Flatten positions at 3:45 PM
    if current_time.hour >= 15 and current_time.minute >= 45:
        if actual_position > 0:
            # Use blankly.trunc to ensure size is acceptable
            sell_size = blankly.trunc(
                actual_position, state.variables.precision)
            if sell_size > 0:
                state.interface.market_order(
                    symbol, side='sell', size=sell_size)
        return

    # === DATA EXTRACTION ===
    curr = bars_df.iloc[-1]
    prev = bars_df.iloc[-2]

    # Relative Volume (RV) Calculation
    v_sma = bars_df['volume'].rolling(window=20).mean().iloc[-1]
    relative_volume = curr['volume'] / v_sma if v_sma > 0 else 0

    is_green = curr['close'] > curr['open']
    is_red = curr['close'] < curr['open']
    broke_prev_high = curr['close'] > prev['high']

    # === SIGNAL LOGIC ===
    # Entry: High relative volume + Bullish Breakout
    buy_signal = relative_volume > 1.2 and is_green and broke_prev_high
    climax_exit = relative_volume > 2.5 and is_red

    # === EXECUTION ===
    # --- LONG ENTRY ---
    if actual_position <= 0 and buy_signal:
        cash = state.interface.cash
        # FIX: Ensure buy_size is truncated to the correct precision
        raw_size = cash / price
        buy_size = blankly.trunc(raw_size, state.variables.precision)

        if buy_size > 0:
            state.interface.market_order(symbol, side='buy', size=buy_size)
            state.variables.entry_price = price
            state.variables.high_water_mark = price

    # --- EXIT & TRAILING STOP ---
    elif actual_position > 0:
        if price > state.variables.high_water_mark:
            state.variables.high_water_mark = price

        pnl_pct = (price - state.variables.entry_price) / \
            state.variables.entry_price
        drop_from_peak = (state.variables.high_water_mark -
                          price) / state.variables.high_water_mark

        should_exit = False
        if drop_from_peak > 0.0075:
            should_exit = True  # Trailing Stop 0.75%
        if pnl_pct < -0.012:
            should_exit = True         # Hard Stop 1.2%
        if climax_exit:
            should_exit = True              # Volume Climax

        if should_exit:
            sell_size = blankly.trunc(
                actual_position, state.variables.precision)
            if sell_size > 0:
                state.interface.market_order(
                    symbol, side='sell', size=sell_size)
                state.variables.high_water_mark = 0
                state.variables.entry_price = 0


def init(symbol, state: blankly.StrategyState):
    # Fetch precision from the exchange
    increment = next(product['base_increment'] for product in state.interface.get_products(
    ) if product['symbol'] == symbol)
    # Convert scientific notation or float to precision integer
    state.variables.precision = blankly.utils.increment_to_precision(increment)
    state.variables.high_water_mark = 0
    state.variables.entry_price = 0


if __name__ == "__main__":
    exchange = blankly.Alpaca(portfolio_name="parmin-key")
    strategy = blankly.Strategy(exchange)
    strategy.add_price_event(price_event, symbol='SPY',
                             resolution='15m', init=init)

    results = strategy.backtest(to='1y', initial_values={'USD': 1000})
    print(results.get_metrics())
