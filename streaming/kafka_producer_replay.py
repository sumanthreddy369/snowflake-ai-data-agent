"""
Replays IBM's synthetic credit card transactions dataset onto a Kafka topic at
(sped-up) real-time speed, so downstream systems (Snowflake's Kafka Connector,
or a Databricks Structured Streaming job) see a genuinely continuous stream
instead of a batch file load.

Dataset: Kaggle "Credit Card Transactions" (IBM TabFormer), columns:
User, Card, Year, Month, Day, Time, Amount, Use Chip, Merchant Name,
Merchant City, Merchant State, Zip, MCC, Errors?, Is Fraud?

Each row is remapped onto this project's transaction schema
(sql/02_bronze/bronze_tables.sql -> RAW_TRANSACTIONS) before publishing, so the
Kafka Connector can write straight into Bronze with no extra transformation.
"""

import argparse
import json
import time
import uuid
from datetime import datetime

import pandas as pd
from kafka import KafkaProducer


def to_transaction_ts(row) -> datetime:
    return datetime.strptime(
        f"{int(row['Year'])}-{int(row['Month']):02d}-{int(row['Day']):02d} {row['Time']}",
        "%Y-%m-%d %H:%M",
    )


def to_bronze_record(row, transaction_ts: datetime) -> dict:
    amount = float(str(row["Amount"]).replace("$", "").replace(",", ""))
    has_error = isinstance(row.get("Errors?"), str) and row["Errors?"].strip() != ""
    return {
        "transaction_id": str(uuid.uuid4()),
        "customer_id": f"CUST_{row['User']}_{row['Card']}",
        "merchant_id": str(row["Merchant Name"]),
        "transaction_ts": transaction_ts.isoformat(),
        "amount": amount,
        "transaction_status": "DECLINED" if has_error else "APPROVED",
        "is_fraud": str(row["Is Fraud?"]).strip().lower() == "yes",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", default="data/transactions.csv", help="Path to the IBM dataset CSV")
    parser.add_argument("--bootstrap-servers", default="localhost:9092")
    parser.add_argument("--topic", default="card-transactions")
    parser.add_argument(
        "--speedup",
        type=float,
        default=3600.0,
        help="Compress real-world time gaps by this factor (default: 1 sim-hour per real second)",
    )
    parser.add_argument("--limit", type=int, default=None, help="Optional row cap for a quick test run")
    args = parser.parse_args()

    df = pd.read_csv(args.csv)
    if args.limit:
        df = df.head(args.limit)

    df["transaction_ts"] = df.apply(to_transaction_ts, axis=1)
    df = df.sort_values("transaction_ts").reset_index(drop=True)

    producer = KafkaProducer(
        bootstrap_servers=args.bootstrap_servers,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
    )

    prev_ts = None
    for _, row in df.iterrows():
        ts = row["transaction_ts"]
        if prev_ts is not None:
            gap_seconds = (ts - prev_ts).total_seconds()
            time.sleep(max(0.0, gap_seconds / args.speedup))
        prev_ts = ts

        record = to_bronze_record(row, ts)
        producer.send(args.topic, value=record, key=record["customer_id"].encode("utf-8"))
        print(f"sent {record['transaction_id']} at {record['transaction_ts']}")

    producer.flush()


if __name__ == "__main__":
    main()
