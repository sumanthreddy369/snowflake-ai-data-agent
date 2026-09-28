"""
Generates a small, schema-accurate sample of news documents -- the document
source for RAG (sql/04_documents, Cortex Search) -- so the search/citations
pipeline can be exercised without hitting Alpaca's News API. Real news comes
from backfill_news.py, which pulls the same fields from Alpaca's actual
/v1beta1/news endpoint using the same Alpaca account already used for market
data (no new vendor needed).
"""

import csv
import logging
import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from schemas import NewsRecord

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("generate_sample_news")

random.seed(7)

SYMBOLS = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"]
HEADLINE_TEMPLATES = [
    ("{sym} beats quarterly earnings estimates, shares rise", "positive"),
    ("{sym} announces new product line at annual event", "neutral"),
    ("{sym} faces regulatory scrutiny over data practices", "negative"),
    ("Analysts upgrade {sym} price target after strong guidance", "positive"),
    ("{sym} supply chain disruption raises cost concerns", "negative"),
    ("{sym} board approves expanded share buyback program", "positive"),
]
SOURCES = ["Reuters", "Bloomberg", "MarketWatch", "Benzinga"]


def generate_news(n_per_symbol: int = 8) -> list[NewsRecord]:
    now = datetime.now(ZoneInfo("UTC"))
    records = []
    news_id = 0
    for symbol in SYMBOLS:
        for _ in range(n_per_symbol):
            headline_template, tone = random.choice(HEADLINE_TEMPLATES)
            headline = headline_template.format(sym=symbol)
            news_id += 1
            published_at = now - timedelta(hours=random.uniform(0, 24 * 14))
            records.append(
                NewsRecord(
                    news_id=str(news_id),
                    headline=headline,
                    summary=f"{headline}. Market reaction has been {tone} so far.",
                    content=(
                        f"{headline}. This is a synthetic sample article standing in for "
                        f"real coverage -- see streaming/backfill_news.py to pull the real "
                        f"thing from Alpaca's News API. Sentiment leaning {tone}."
                    ),
                    symbols=symbol,
                    source=random.choice(SOURCES),
                    url=f"https://example.com/news/{news_id}",
                    published_at=published_at,
                )
            )
    records.sort(key=lambda r: r.published_at)
    return records


def write_csv(path, models):
    rows = [m.model_dump(mode="json") for m in models]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    logger.info("wrote %d rows to %s", len(rows), path)


if __name__ == "__main__":
    write_csv("data/sample_news.csv", generate_news())
