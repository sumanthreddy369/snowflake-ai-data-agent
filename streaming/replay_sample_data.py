"""
Replays the generated sample_bars.csv / sample_trades.csv onto the same Kafka
topics alpaca_stream_producer.py would use, at a controlled pace, sorted by
timestamp. Use this to test the Snowflake Kafka Connector end-to-end without
an Alpaca account or while markets are closed.
"""

import argparse
import csv
import json
import time
from datetime import datetime

from kafka import KafkaProducer


def load_rows(path, ts_field):
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        row["_ts"] = datetime.fromisoformat(row[ts_field])
    rows.sort(key=lambda r: r["_ts"])
    return rows


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

    bars = load_rows(args.bars_csv, "bar_ts")
    trades = load_rows(args.trades_csv, "trade_ts")
    if args.limit:
        bars, trades = bars[: args.limit], trades[: args.limit]

    merged = sorted(
        [("bar", r) for r in bars] + [("trade", r) for r in trades],
        key=lambda item: item[1]["_ts"],
    )

    producer = KafkaProducer(
        bootstrap_servers=args.bootstrap_servers,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )

    prev_ts = None
    for kind, row in merged:
        ts = row.pop("_ts")
        if prev_ts is not None:
            time.sleep(max(0.0, (ts - prev_ts).total_seconds() / args.speedup))
        prev_ts = ts

        topic = args.bars_topic if kind == "bar" else args.trades_topic
        producer.send(topic, value=row, key=row["symbol"].encode("utf-8"))
        print(kind, row)

    producer.flush()


if __name__ == "__main__":
    main()
