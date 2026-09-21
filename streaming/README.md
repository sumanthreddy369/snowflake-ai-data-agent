# Real-time ingestion (Option B)

`sql/01_ingest/snowpipe_setup.sql` covers **file-based** Snowpipe: files land in
a stage, auto-ingest fires on a storage event. That's near-real-time (seconds to
low minutes) and file-oriented — fine for batch drops, not for a live feed.

For genuine real-time, this folder replaces that path with:

1. **A Kafka producer that replays a real dataset at real-time speed** —
   [`kafka_producer_replay.py`](kafka_producer_replay.py) reads IBM's synthetic
   credit card transactions dataset (Kaggle: "Credit Card Transactions" /
   TabFormer, ~24M rows) row by row, sorted by its original timestamp, and
   publishes each row to a Kafka topic at a pace that mirrors the original
   time gaps (compressed by a configurable speed-up factor). This is the
   standard way fraud teams load-test a streaming pipeline before it ever
   touches a live transaction feed, which is never public.
2. **The Snowflake Kafka Connector, running in Snowpipe Streaming mode** —
   [`snowflake_kafka_connector.json`](snowflake_kafka_connector.json) is a
   Kafka Connect sink config that consumes that topic and writes rows straight
   into `BANK_AGENT.BRONZE.RAW_TRANSACTIONS` with second-level latency, no
   stage or COPY INTO involved.

## Why this matters (Snowpipe vs Snowpipe Streaming vs Databricks)

| | Snowpipe (file-based) | Snowpipe Streaming (this folder) | Databricks Structured Streaming |
|---|---|---|---|
| Unit of ingestion | Files in a stage | Individual rows/events via Kafka | Individual rows/events via Kafka or Auto Loader |
| Latency | Seconds–minutes (batch-triggered) | Seconds (row-level) | Sub-second to seconds (continuous micro-batch) |
| What triggers it | A cloud storage event (new file) | A row arriving on the Kafka topic | A new event/file arriving |
| Where the logic lives | `COPY INTO` inside the pipe definition | Kafka Connect sink config | Code (PySpark/DLT) you write and run |

The takeaway for the portfolio story: Snowflake bolts real-time on as a Kafka
Connector sitting outside the warehouse; Databricks treats streaming as a native
first-class execution mode of the same engine that runs batch. Both get you to
"real-time," but the underlying architecture — and how much code you own vs.
configure — is genuinely different, which is the point of running both projects.

## Setup

1. Download the dataset from Kaggle ("Credit Card Transactions" / TabFormer) and
   place the CSV at `streaming/data/transactions.csv` (gitignored — see the
   dataset's Kaggle license before redistributing it).
2. `pip install kafka-python pandas` and run a local Kafka broker (e.g.
   `docker run -p 9092:9092 apache/kafka`).
3. Run `python kafka_producer_replay.py` to start streaming rows onto the
   `card-transactions` topic.
4. Fill in `snowflake_kafka_connector.json` with your account details and a
   key-pair auth key, then deploy it to a running Kafka Connect worker
   (`curl -X POST -H "Content-Type: application/json" --data @snowflake_kafka_connector.json http://localhost:8083/connectors`).
5. Rows should start appearing in `BANK_AGENT.BRONZE.RAW_TRANSACTIONS` within
   seconds — the same Silver Streams+Tasks in `sql/03_silver` pick them up
   exactly as they would file-based Snowpipe rows.
