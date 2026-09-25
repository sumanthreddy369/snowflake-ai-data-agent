"""
Replays the generated sample_bars.csv / sample_trades.csv onto the same Kafka
topics alpaca_stream_producer.py would use, at a controlled pace, sorted by
timestamp. Use this to test the Snowflake Kafka Connector end-to-end without
an Alpaca account or while markets are closed. Each row is re-validated
against schemas.py before being sent, matching the live producer's behavior.
"""

import argparse
import csv
import json
import logging
import time

from kafka import KafkaProducer
from pydantic import ValidationError

from schemas import BarRecord, TradeRecord

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("replay_sample_data")


def load_bars(path):
    with open(path, newline="") as f:
        return [BarRecord(**row) for row in csv.DictReader(f)]


def load_trades(path):
    with open(path, newline="") as f:
        return [TradeRecord(**row) for row in csv.DictReader(f)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars-csv", default="data/sample_bars.csv")
    parser.add_argument("--trades-csv", default="data/sample_trades.csv")
    parser.add_argument("--bootstrap-servers", default="localhost:9092")
    parser.add_argument("--trades-topic", default="market-trades")
    parser.add_argument("--bars-topic", default="market-bars")
    parser.add_argument("--speedup", type=float, default=60.0, help="Compress real-time gaps by this factor")
    parser.add_argument("--limit", type=int, default=None, help="Optional row cap per stream for a quick test")
    args = parser.parse_args()

    try:
        bars = load_bars(args.bars_csv)
        trades = load_trades(args.trades_csv)
    except ValidationError as e:
        logger.error("sample data failed schema validation: %s", e)
        raise
    if args.limit:
        bars, trades = bars[: args.limit], trades[: args.limit]

    merged = sorted(
        [("bar", r, r.bar_ts) for r in bars] + [("trade", r, r.trade_ts) for r in trades],
        key=lambda item: item[2],
    )

    producer = KafkaProducer(
        bootstrap_servers=args.bootstrap_servers,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )

    prev_ts = None
    for kind, record, ts in merged:
        if prev_ts is not None:
            time.sleep(max(0.0, (ts - prev_ts).total_seconds() / args.speedup))
        prev_ts = ts

        topic = args.bars_topic if kind == "bar" else args.trades_topic
        producer.send(topic, value=record.model_dump(mode="json"), key=record.symbol.encode("utf-8"))
        logger.info("%s %s", kind, record.model_dump_json())

    producer.flush()


if __name__ == "__main__":
    main()
