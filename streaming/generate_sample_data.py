"""
Generates a small, schema-accurate sample of trades and minute bars, so the
pipeline can be run end-to-end without an Alpaca account or waiting for market
hours. Prices follow a simple random walk per symbol across one trading day
(9:30-16:00 US/Eastern, 390 minutes, correctly converted to UTC for storage);
trades are a handful of prints per bar clustered around that bar's OHLC range.
Every row is validated against schemas.py before being written, so a bug here
fails loudly instead of producing bad Bronze data.

Swap this for streaming/alpaca_stream_producer.py once you have a free Alpaca
API key and want genuinely live data; the column layout is identical either
way, so nothing downstream needs to change.
"""

import csv
import logging
import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from schemas import BarRecord, SymbolRecord, TradeRecord

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("generate_sample_data")

random.seed(42)

SYMBOLS = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"]
START_PRICES = {"AAPL": 225.0, "MSFT": 430.0, "GOOGL": 175.0, "AMZN": 190.0, "TSLA": 250.0}
MARKET_OPEN_ET = datetime.now(ZoneInfo("America/New_York")).replace(
    hour=9, minute=30, second=0, microsecond=0
)
BAR_MINUTES = 390  # one trading day, 9:30-16:00 ET
TRADES_PER_BAR = 4


def generate_bars_and_trades():
    bars, trades = [], []
    trade_id = 0

    for symbol in SYMBOLS:
        price = START_PRICES[symbol]
        for minute in range(BAR_MINUTES):
            bar_start_et = MARKET_OPEN_ET + timedelta(minutes=minute)
            bar_start_utc = bar_start_et.astimezone(ZoneInfo("UTC"))
            open_price = price
            prints = [open_price]
            for _ in range(TRADES_PER_BAR):
                price = max(0.01, price + random.gauss(0, price * 0.001))
                prints.append(price)
            close_price = prints[-1]
            high = max(prints)
            low = min(prints)
            volume = random.randint(500, 50000)

            bar = BarRecord(
                symbol=symbol,
                bar_ts=bar_start_utc,
                open=round(open_price, 4),
                high=round(high, 4),
                low=round(low, 4),
                close=round(close_price, 4),
                volume=volume,
                vwap=round(sum(prints) / len(prints), 4),
                trade_count=TRADES_PER_BAR,
            )
            bars.append(bar)

            for i, p in enumerate(prints[1:], start=1):
                trade_id += 1
                trade_ts_utc = bar_start_utc + timedelta(seconds=(60 // TRADES_PER_BAR) * i)
                trades.append(
                    TradeRecord(
                        trade_id=str(trade_id),
                        symbol=symbol,
                        price=round(p, 4),
                        size=random.choice([10, 25, 50, 100, 200, 500]),
                        exchange_code="V",
                        conditions="@",
                        trade_ts=trade_ts_utc,
                    )
                )

    bars.sort(key=lambda r: r.bar_ts)
    trades.sort(key=lambda r: r.trade_ts)
    return bars, trades


def write_csv(path, models):
    rows = [m.model_dump(mode="json") for m in models]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    logger.info("wrote %d rows to %s", len(rows), path)


def write_symbols_csv(path):
    sectors = {"AAPL": "Technology", "MSFT": "Technology", "GOOGL": "Communication Services",
               "AMZN": "Consumer Discretionary", "TSLA": "Consumer Discretionary"}
    names = {"AAPL": "Apple Inc.", "MSFT": "Microsoft Corp.", "GOOGL": "Alphabet Inc.",
             "AMZN": "Amazon.com Inc.", "TSLA": "Tesla Inc."}
    symbols = [
        SymbolRecord(symbol=s, company_name=names[s], sector=sectors[s], exchange="NASDAQ", is_active=True)
        for s in SYMBOLS
    ]
    write_csv(path, symbols)


if __name__ == "__main__":
    bars, trades = generate_bars_and_trades()
    write_csv("data/sample_bars.csv", bars)
    write_csv("data/sample_trades.csv", trades)
    write_symbols_csv("data/sample_symbols.csv")
