"""
Backfills real financial news from Alpaca's News API (/v1beta1/news) --
the same Alpaca account already used for market data, no new vendor. Pulls
concurrently across symbols (asyncio + httpx, same pattern as
backfill_historical.py) and writes a CSV matching the Bronze documents
schema (sql/04_documents/documents_and_search.sql -> RAW_NEWS), which Cortex
Search indexes for RAG.

Docs: https://docs.alpaca.markets/us/docs/real-time-stock-pricing-data (News API)
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

from schemas import NewsRecord

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_news")

NEWS_URL = "https://data.alpaca.markets/v1beta1/news"


def auth_headers() -> dict:
    return {
        "APCA-API-KEY-ID": os.environ["ALPACA_API_KEY"],
        "APCA-API-SECRET-KEY": os.environ["ALPACA_API_SECRET"],
    }


@retry(wait=wait_exponential(multiplier=1, min=2, max=30), stop=stop_after_attempt(5))
async def fetch_news(client: httpx.AsyncClient, symbols: list[str], start: str, end: str) -> list[NewsRecord]:
    records: list[NewsRecord] = []
    page_token = None
    while True:
        params = {"symbols": ",".join(symbols), "start": start, "end": end, "limit": 50, "include_content": "true"}
        if page_token:
            params["page_token"] = page_token
        resp = await client.get(NEWS_URL, params=params, headers=auth_headers())
        resp.raise_for_status()
        payload = resp.json()

        for item in payload.get("news", []):
            try:
                records.append(
                    NewsRecord(
                        news_id=str(item["id"]),
                        headline=item.get("headline", ""),
                        summary=item.get("summary", ""),
                        content=item.get("content", ""),
                        symbols=",".join(item.get("symbols", [])),
                        source=item.get("source", ""),
                        url=item.get("url", ""),
                        published_at=item["created_at"],
                    )
                )
            except ValidationError as e:
                logger.warning("dropping invalid news item %s: %s", item.get("id"), e)

        page_token = payload.get("next_page_token")
        if not page_token:
            break

    logger.info("fetched %d news items", len(records))
    return records


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
    parser.add_argument("--start", required=True, help="e.g. 2026-08-01")
    parser.add_argument("--end", required=True, help="e.g. 2026-09-01")
    parser.add_argument("--out", default="data/backfill_news.csv")
    args = parser.parse_args()

    async def run():
        async with httpx.AsyncClient(timeout=30.0) as client:
            return await fetch_news(client, args.symbols, args.start, args.end)

    news = asyncio.run(run())
    write_csv(args.out, news)
    logger.info("upload this file to the GCS path for RAW_NEWS to trigger Snowpipe")


if __name__ == "__main__":
    main()
