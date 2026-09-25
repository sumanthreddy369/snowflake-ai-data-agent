# Real-time ingestion

`sql/01_ingest/snowpipe_setup.sql` covers **batch backfill**: historical bars
and the symbol reference table, loaded as files from Google Cloud Storage
(chosen over the more common S3 pattern to diversify cloud experience —
Snowflake's GCS storage integration is structurally the same, just a
different auth model underneath). This folder covers the **live** path:
real-time trades and minute bars from Alpaca's free market data feed,
flowing through Kafka into Snowflake via Snowpipe Streaming.

Every record in this folder — live or offline — is validated against a
shared Pydantic contract in [`schemas.py`](schemas.py) before it's sent
anywhere, so a malformed message fails loudly here instead of silently
corrupting Bronze.

## Two ways to run it

1. **Live (recommended once you have a free Alpaca account)** —
   [`alpaca_stream_producer.py`](alpaca_stream_producer.py) connects to
   Alpaca's IEX websocket feed (free, real, no compliance wall — see
   [docs](https://docs.alpaca.markets/us/docs/websocket-streaming)),
   subscribes to trades + minute bars for a symbol list, and republishes each
   message onto Kafka topics after remapping onto this project's Bronze
   schema. Sign up free at [alpaca.markets](https://alpaca.markets/) and set
   `ALPACA_API_KEY` / `ALPACA_API_SECRET`.
2. **Offline sample (works with no account, any time of day)** —
   [`generate_sample_data.py`](generate_sample_data.py) produces
   `data/sample_bars.csv`, `data/sample_trades.csv`, and
   `data/sample_symbols.csv` (checked into this repo, ~10k rows total, a
   random-walk simulation of one trading day across 5 symbols), and
   [`replay_sample_data.py`](replay_sample_data.py) publishes them onto the
   same Kafka topics at a controlled pace. Use this to test the Snowflake
   Kafka Connector end-to-end before touching a live feed, or whenever the
   market is closed.

Both scripts publish to the same two topics (`market-trades`, `market-bars`),
so nothing downstream — the Kafka Connector, Bronze, Silver, Gold — needs to
know or care which one is running. The live producer also retries a dropped
websocket connection with exponential backoff (`tenacity`) instead of dying,
and both scripts emit structured log lines instead of bare `print()`.

## Batch backfill

[`backfill_historical.py`](backfill_historical.py) is the batch counterpart:
it concurrently (`asyncio` + `httpx`, one task per symbol) pulls historical
daily bars and asset metadata from Alpaca's REST API and writes CSVs matching
the Bronze schema, ready to upload to the GCS paths in
`sql/01_ingest/snowpipe_setup.sql`:

```bash
ALPACA_API_KEY=... ALPACA_API_SECRET=... python backfill_historical.py \
  --start 2026-01-01 --end 2026-09-01
```

## Why this matters (Snowpipe vs Snowpipe Streaming vs Databricks)

| | Snowpipe (file-based) | Snowpipe Streaming (this folder) | Databricks Structured Streaming |
|---|---|---|---|
| Unit of ingestion | Files in a stage | Individual rows/events via Kafka | Individual rows/events via Kafka or Auto Loader |
| Latency | Seconds–minutes (batch-triggered) | Seconds (row-level) | Sub-second to seconds (continuous micro-batch) |
| What triggers it | A cloud storage event (new file) | A row arriving on the Kafka topic | A new event/file arriving |
| Where the logic lives | `COPY INTO` inside the pipe definition | Kafka Connect sink config | Code (PySpark/DLT) you write and run |

The takeaway for the portfolio story: Snowflake bolts real-time on as a Kafka
Connector sitting outside the warehouse; Databricks treats streaming as a
native first-class execution mode of the same engine that runs batch. Both
get you to "real-time," but the underlying architecture — and how much code
you own vs. configure — is genuinely different.

## Setup

1. `pip install -r ../requirements.txt` and run a local Kafka broker (e.g.
   `docker run -p 9092:9092 apache/kafka`).
2. Test with the offline sample first:
   `python replay_sample_data.py --limit 200 --speedup 300`
3. Once that's flowing, switch to live data (only works during US market
   hours, 9:30-16:00 ET):
   `ALPACA_API_KEY=... ALPACA_API_SECRET=... python alpaca_stream_producer.py`
4. Fill in `snowflake_kafka_connector.json` with your account details and a
   key-pair auth key, then deploy it to a running Kafka Connect worker
   (`curl -X POST -H "Content-Type: application/json" --data @snowflake_kafka_connector.json http://localhost:8083/connectors`).
5. Rows should start appearing in `MARKET_AGENT.BRONZE.RAW_TRADES` and
   `RAW_BARS` within seconds — the same Silver Streams+Tasks in
   `sql/03_silver` pick them up exactly as they would file-based Snowpipe rows.
