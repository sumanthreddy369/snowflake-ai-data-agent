# Snowflake AI Data Agent

Project 1 of a two-part portfolio series (Snowflake + Databricks, built in
separate repos) proving that messy raw data can be made **accurate and
understandable to an AI agent** — not just piped through a warehouse.

Domain: **real-time U.S. equities market data** — trades, minute bars (OHLCV),
and a symbol reference table. Chosen over synthetic finance data because it's
genuinely real (Alpaca's free IEX feed, no compliance wall, no synthetic
stand-in required) and technically demanding in ways synthetic data isn't:
market hours, timezones, corporate actions, and real streaming volume. It's
also one of the most recognizable finance verticals for DE/DA hiring, and
"AI agent over real-time market/risk data" is a fast-growing category at
trading desks and fintechs right now. See
[`docs/PORTFOLIO_BRIEF.md`](docs/PORTFOLIO_BRIEF.md) for the full reasoning
history behind this and earlier domain decisions.

The companion Databricks project (separate repo, being built in parallel)
covers healthcare instead, to diversify the portfolio across two regulated
industries and Databricks' actual differentiators (unstructured data, native
streaming, Delta Live Tables).

Cloud storage runs on **Google Cloud Storage** rather than S3, deliberately
different from other projects in this portfolio. The Python pieces
(`streaming/`, `agent/`) also reuse patterns from those other projects —
Pydantic contracts, `tenacity` retries, `httpx`/`asyncio` for concurrent API
calls, structured logging, and Langfuse tracing around the one LLM-adjacent
call this project makes (Cortex Analyst) — so the stack is consistent across
the portfolio even where the domain and cloud provider differ.

## Pipeline

| Step | What happens | Tool | Where |
|---|---|---|---|
| 1. Ingest | Trades/bars stream live; symbols & history backfill in batch | Alpaca feed → Kafka → Snowpipe Streaming (live), Snowpipe (batch) | [`streaming/`](streaming/), [`sql/01_ingest/snowpipe_setup.sql`](sql/01_ingest/snowpipe_setup.sql) |
| 2. Bronze | Raw data lands untouched | Snowflake raw tables | [`sql/02_bronze/bronze_tables.sql`](sql/02_bronze/bronze_tables.sql) |
| 3. Silver | Clean, dedupe, standardize | Streams + Tasks | [`sql/03_silver/streams_and_tasks.sql`](sql/03_silver/streams_and_tasks.sql) |
| 4. Gold | Business-ready star schema (price/volume/return/volatility) | dbt | [`dbt/models/marts`](dbt/models/marts) |
| 5. Semantic Layer | Define "return", "volatility", "VWAP" | Cortex Analyst YAML | [`semantic_layer/semantic_model.yaml`](semantic_layer/semantic_model.yaml) |
| 6. Agent | Ask questions in plain English | Cortex Analyst | Snowsight → Cortex Analyst, pointed at the semantic model |
| 7. Governance | Control who/what can access real-time vs. delayed data | RBAC + Row Access Policy | [`sql/07_governance/rbac_and_masking.sql`](sql/07_governance/rbac_and_masking.sql) |
| 8. Validate | Check the agent's answers are correct | Manual SQL comparison | [`sql/08_validation/validation_queries.sql`](sql/08_validation/validation_queries.sql) |

## Guardrails

Cutting across all 8 steps rather than living in one of them — see
[`sql/09_guardrails/cost_and_access_guardrails.sql`](sql/09_guardrails/cost_and_access_guardrails.sql)
unless noted otherwise:

| Guardrail | What it prevents | Where |
|---|---|---|
| Dead-letter queue | A malformed message silently vanishing instead of being inspectable | `streaming/alpaca_stream_producer.py`, `streaming/replay_sample_data.py` → `market-data-dlq` topic |
| OHLC sanity test | A data bug (`high < low`, negative price) being trusted as a real data point | `dbt/tests/assert_bar_ohlc_consistency.sql` (fails the build) |
| Circuit-breaker flag | A bad tick (or a real 10%+ move) being silently baked into an aggregate answer with no way to know | `is_suspect` column on `fct_bars` (flags, doesn't drop) + `suspect_bars_today` monitoring query |
| Dedicated agent warehouse + statement timeout | A runaway or malicious NL-generated query burning shared compute or running forever | `ANALYST_WH`, 30s statement timeout |
| Resource Monitor | One bad session blowing through the account's credit budget | `ANALYST_AGENT_MONITOR`, hard-suspends at 100% of a monthly quota |
| Append-only audit log | The agent's own query history being edited after the fact | `MARKET_AGENT.GOVERNANCE.AGENT_QUERY_AUDIT_LOG` — `ANALYST_AGENT` can `INSERT`, never `UPDATE`/`DELETE` |
| Row Access Policy | The agent seeing real-time prices it isn't licensed to show | `sql/07_governance/rbac_and_masking.sql` (already covered under Governance above) |

## Layout

```
snowflake-ai-data-agent/
├── sql/
│   ├── 01_ingest/snowpipe_setup.sql        # batch backfill: symbols + historical bars
│   ├── 02_bronze/bronze_tables.sql         # raw landing tables, untouched
│   ├── 03_silver/streams_and_tasks.sql     # dedupe/standardize via Streams+Tasks
│   ├── 07_governance/rbac_and_masking.sql  # roles, grants, delayed-data row access policy
│   ├── 08_validation/validation_queries.sql
│   └── 09_guardrails/cost_and_access_guardrails.sql  # resource monitor, timeouts, audit log
├── streaming/                              # live path: Alpaca -> Kafka -> Snowpipe Streaming
│   ├── schemas.py                          # shared Pydantic contracts for trades/bars/symbols
│   ├── alpaca_stream_producer.py           # live feed (tenacity retries, structured logging)
│   ├── generate_sample_data.py / replay_sample_data.py  # offline fallback, no account needed
│   ├── backfill_historical.py              # async/httpx batch backfill -> GCS -> Snowpipe
│   └── snowflake_kafka_connector.json
├── agent/                                  # instrumented Cortex Analyst REST client
│   ├── cortex_client.py                    # httpx + tenacity + Langfuse tracing
│   └── schemas.py
├── dbt/
│   ├── dbt_project.yml
│   ├── profiles.yml.example
│   ├── models/
│   │   ├── staging/     # 1:1 views over Silver (trades, bars, symbols)
│   │   └── marts/       # Gold star schema (dim_symbols, dim_date, fct_trades, fct_bars)
│   └── tests/assert_bar_ohlc_consistency.sql  # guardrail: fails the build on bad OHLC data
├── semantic_layer/
│   └── semantic_model.yaml                 # Cortex Analyst semantic model
├── requirements.txt
└── docs/
    └── PORTFOLIO_BRIEF.md                  # full reasoning history, for writeups/resume
```

## Setup order

1. Run `sql/02_bronze` to create the raw tables.
2. Set up the live/offline streaming path — follow
   [`streaming/README.md`](streaming/README.md) (start with the offline
   sample replay, no Alpaca account needed, then switch to the live feed).
3. Run `sql/03_silver` to create the Silver schema, the Streams on Bronze, and
   the Tasks that merge changes in on a schedule.
4. `cd dbt && dbt run` to build the Gold star schema from Silver (edit
   `profiles.yml.example` → `~/.dbt/profiles.yml` with your account first).
5. Upload `semantic_layer/semantic_model.yaml` in Snowsight (AI & ML → Cortex
   Analyst) pointed at the Gold tables, or reference it from a Streamlit/API app.
6. Run `sql/07_governance` to apply the delayed-data row access policy and
   restrict roles before opening the agent up to real users — the
   ANALYST_AGENT role should never see true real-time prices.
7. Run `sql/09_guardrails` to create the dedicated agent warehouse, its
   Resource Monitor, and the append-only audit log table — do this before
   pointing real users at the agent, not after.
8. Ask the agent a question in Snowsight, or via
   [`agent/cortex_client.py`](agent/cortex_client.py) if you want every query
   traced through Langfuse and logged to the audit table; then run the
   matching query in `sql/08_validation/validation_queries.sql` and diff the
   numbers by hand. Run `dbt test` periodically to catch OHLC data bugs, and
   check the `suspect_bars_today` query for flagged anomalies.

## Status

Scaffold only — SQL and dbt models are structurally complete and runnable
against a real Snowflake account. The offline sample data lets you validate
the whole pipeline before connecting a live Alpaca feed.
