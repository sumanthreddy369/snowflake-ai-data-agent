"""
Backfills historical daily bars and the symbol reference table from Alpaca's
REST API, concurrently across symbols via asyncio + httpx, writing CSVs that
match the Bronze schema for the batch Snowpipe path
(sql/01_ingest/snowpipe_setup.sql -> BARS_BACKFILL_PIPE / SYMBOLS_PIPE).

This is the batch complement to the live streaming path in this folder: use
it once, up front, to load history before the live feed starts filling in
new bars going forward.

Docs: https://docs.alpaca.markets/us/reference/stockbars
Env vars: ALPACA_API_KEY, ALPACA_API_SECRET
"""

import argparse
import asyncio
import csv
import logging
import os

import httpx
from pydantic import ValidationError
from tenacity import retry, stop_after_attempt, wait_exponential

from schemas import BarRecord, SymbolRecord

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_historical")

BARS_URL = "https://data.alpaca.markets/v2/stocks/bars"
ASSETS_URL = "https://paper-api.alpaca.markets/v2/assets"


def auth_headers() -> dict:
    return {
        "APCA-API-KEY-ID": os.environ["ALPACA_API_KEY"],
        "APCA-API-SECRET-KEY": os.environ["ALPACA_API_SECRET"],
    }


@retry(wait=wait_exponential(multiplier=1, min=2, max=30), stop=stop_after_attempt(5))
async def fetch_bars(client: httpx.AsyncClient, symbol: str, start: str, end: str, timeframe: str) -> list[BarRecord]:
    records: list[BarRecord] = []
    page_token = None
    while True:
        params = {"symbols": symbol, "timeframe": timeframe, "start": start, "end": end, "limit": 1000}
        if page_token:
            params["page_token"] = page_token
        resp = await client.get(BARS_URL, params=params, headers=auth_headers())
        resp.raise_for_status()
        payload = resp.json()

        for bar in payload.get("bars", {}).get(symbol, []):
            try:
                records.append(
                    BarRecord(
                        symbol=symbol,
                        bar_ts=bar["t"],
                        open=bar["o"],
                        high=bar["h"],
                        low=bar["l"],
                        close=bar["c"],
                        volume=bar["v"],
                        vwap=bar.get("vw"),
                        trade_count=bar.get("n"),
                    )
                )
            except ValidationError as e:
                logger.warning("dropping invalid bar for %s: %s", symbol, e)

        page_token = payload.get("next_page_token")
        if not page_token:
            break

    logger.info("fetched %d bars for %s", len(records), symbol)
    return records


async def fetch_symbol_metadata(client: httpx.AsyncClient, symbol: str) -> SymbolRecord | None:
    resp = await client.get(f"{ASSETS_URL}/{symbol}", headers=auth_headers())
    if resp.status_code == 404:
        logger.warning("no asset metadata found for %s", symbol)
        return None
    resp.raise_for_status()
    asset = resp.json()
    return SymbolRecord(
        symbol=asset["symbol"],
        company_name=asset.get("name", asset["symbol"]),
        sector="Unknown",  # Alpaca's /v2/assets doesn't return sector; enrich from another source if needed
        exchange=asset.get("exchange", "UNKNOWN"),
        is_active=asset.get("status") == "active",
    )


async def backfill(symbols: list[str], start: str, end: str, timeframe: str):
    async with httpx.AsyncClient(timeout=30.0) as client:
        bar_results, symbol_results = await asyncio.gather(
            asyncio.gather(*(fetch_bars(client, s, start, end, timeframe) for s in symbols)),
            asyncio.gather(*(fetch_symbol_metadata(client, s) for s in symbols)),
        )

    all_bars = [b for group in bar_results for b in group]
    all_symbols = [s for s in symbol_results if s is not None]
    return all_bars, all_symbols


def write_csv(path, models):
    if not models:
        logger.warning("no rows to write for %s", path)
        return
    rows = [m.model_dump(mode="json") for m in models]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    logger.info("wrote %d rows to %s", len(rows), path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", nargs="+", default=["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"])
    parser.add_argument("--start", required=True, help="e.g. 2026-01-01")
    parser.add_argument("--end", required=True, help="e.g. 2026-09-01")
    parser.add_argument("--timeframe", default="1Day", help="e.g. 1Day, 1Hour, 1Min")
    parser.add_argument("--bars-out", default="data/backfill_bars.csv")
    parser.add_argument("--symbols-out", default="data/backfill_symbols.csv")
    args = parser.parse_args()

    bars, symbols = asyncio.run(backfill(args.symbols, args.start, args.end, args.timeframe))
    write_csv(args.bars_out, bars)
    write_csv(args.symbols_out, symbols)
    logger.info("upload these two files to the GCS paths in sql/01_ingest/snowpipe_setup.sql to trigger Snowpipe")


if __name__ == "__main__":
    main()
