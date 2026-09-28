# Snowflake AI Data Agent

Project 1 of a two-part portfolio series (Snowflake + Databricks, built in
separate repos) proving that messy raw data can be made **accurate and
understandable to an AI agent** — not just piped through a warehouse.

Domain: **real-time U.S. equities market data and news** — trades, minute
bars (OHLCV), a symbol reference table, and recent financial news for RAG.
Chosen over synthetic finance data because it's genuinely real (Alpaca's free
IEX feed and News API, no compliance wall, no synthetic stand-in required)
and technically demanding in ways synthetic data isn't: market hours,
timezones, corporate actions, and real streaming volume. See
[`docs/PORTFOLIO_BRIEF.md`](docs/PORTFOLIO_BRIEF.md) for the full reasoning
history behind this and earlier domain decisions.

The companion Databricks project (separate repo, being built in parallel)
covers healthcare instead, to diversify the portfolio across two regulated
industries and Databricks' actual differentiators (unstructured data, native
streaming, Delta Live Tables).

Cloud storage runs on **Google Cloud Storage** rather than S3, deliberately
different from other projects in this portfolio. The Python pieces also
reuse patterns from those other projects — Pydantic contracts, `tenacity`
retries, `httpx`/`asyncio` for concurrent API calls, structured logging, and
Langfuse tracing around every LLM-adjacent call.

## Architecture

```
Alpaca (trades, bars, news)
        │
        ▼
      Kafka
        │
        ▼
 Snowpipe / Snowpipe Streaming  ◄── GCS (batch backfill)
        │
        ▼
   RAW SNOWFLAKE DATA (Bronze)
        │
        ▼
  Streams + Tasks / Dynamic Tables
        │
        ▼
      dbt  ──────────────────────► Snowpark (ONNX anomaly model)
        │
        ▼
   Gold star schema + News (Silver)
        │
   ┌────┴─────┐
   ▼          ▼
Semantic   Cortex Search
View      (news, citations)
   │          │
   ▼          ▼
Cortex Analyst  ◄─┘
   │
   ▼
Cortex Agent (orchestrates both tools)
   │
   ▼
  MCP server ──► Streamlit UI / FastAPI ──► governed answer
```

Every arrow into "governed answer" passes through the same Row Access Policy
and role restrictions regardless of entry point (Snowsight, the agent client,
the MCP server, the Streamlit app, or the FastAPI service) — governance is
enforced once, at the database layer, not re-implemented per client.

## Pipeline

| Step | What happens | Tool | Where |
|---|---|---|---|
| 1. Ingest | Trades/bars/news stream live or backfill in batch | Alpaca feed → Kafka → Snowpipe Streaming (live), Snowpipe (batch, GCS) | [`streaming/`](streaming/), [`sql/01_ingest/`](sql/01_ingest/) |
| 2. Bronze | Raw data lands untouched | Snowflake raw tables | [`sql/02_bronze/`](sql/02_bronze/) |
| 3. Silver | Clean, dedupe, standardize | Streams + Tasks (Dynamic Tables shown as an alternative) | [`sql/03_silver/`](sql/03_silver/) |
| 4. Gold | Business-ready star schema | dbt | [`dbt/models/marts`](dbt/models/marts) |
| 4b. Documents | News ingested + indexed for retrieval | Cortex Search | [`sql/04_documents/`](sql/04_documents/) |
| 5. Semantic Layer | Define "return", "volatility", "VWAP" | Cortex Analyst YAML + native Semantic View | [`semantic_layer/`](semantic_layer/) |
| 6. Agent | Ask questions in plain English | Cortex Analyst (direct) | [`agent/cortex_client.py`](agent/cortex_client.py) |
| 6b. Multi-tool Agent | Routes between structured data and news search | Cortex Agent | [`sql/10_agent/`](sql/10_agent/), [`agent/cortex_agent_client.py`](agent/cortex_agent_client.py) |
| Agent interop | Expose the agent as callable tools | MCP (FastMCP server) | [`agent/mcp_server.py`](agent/mcp_server.py) |
| ML | Learned anomaly detection, replacing a fixed threshold | Snowpark + ONNX + Model Registry | [`snowpark/`](snowpark/) |
| 7. Governance | Control who/what can access real-time vs. delayed data | RBAC + Row Access Policy | [`sql/07_governance/`](sql/07_governance/) |
| 8. Validate | Check the agent's answers are correct | Manual SQL comparison + dbt tests | [`sql/08_validation/`](sql/08_validation/), [`dbt/tests/`](dbt/tests/) |
| API/UI | Human- and machine-facing entry points | Streamlit + FastAPI | [`ui/`](ui/), [`api/`](api/) |

## Guardrails

Cutting across the pipeline rather than living in one step — see
[`sql/09_guardrails/cost_and_access_guardrails.sql`](sql/09_guardrails/cost_and_access_guardrails.sql)
unless noted otherwise:

| Guardrail | What it prevents | Where |
|---|---|---|
| Dead-letter queue | A malformed message silently vanishing instead of being inspectable | `streaming/*.py` → `market-data-dlq` topic |
| OHLC sanity test | A data bug (`high < low`, negative price) being trusted as a real data point | `dbt/tests/assert_bar_ohlc_consistency.sql` (fails the build) |
| Circuit-breaker flag | A bad tick (or a real 10%+ move) being silently baked into an aggregate answer | `is_suspect` column on `fct_bars` — see also the Snowpark ONNX model, a learned replacement for this fixed threshold |
| Dedicated agent warehouse + statement timeout | A runaway or malicious NL-generated query burning shared compute or running forever | `ANALYST_WH`, 30s statement timeout |
| Resource Monitor | One bad session blowing through the account's credit budget | `ANALYST_AGENT_MONITOR`, hard-suspends at 100% of a monthly quota |
| Append-only audit log | The agent's own query history being edited after the fact | `MARKET_AGENT.GOVERNANCE.AGENT_QUERY_AUDIT_LOG` — shared by both `cortex_client.py` and `cortex_agent_client.py` |
| Row Access Policy | The agent seeing real-time prices it isn't licensed to show, from *any* entry point (Snowsight, agent, MCP, Streamlit, FastAPI) | `sql/07_governance/rbac_and_masking.sql` |

## Layout

```
snowflake-ai-data-agent/
├── sql/
│   ├── 01_ingest/           # Snowpipe (batch, GCS): symbols, historical bars, news
│   ├── 02_bronze/           # raw landing tables, untouched
│   ├── 03_silver/           # Streams+Tasks (main) + Dynamic Tables (alternative, for breadth)
│   ├── 04_documents/        # RAW_NEWS -> SILVER.NEWS -> Cortex Search Service
│   ├── 07_governance/       # roles, grants, delayed-data row access policy
│   ├── 08_validation/       # hand-written SQL twins of every verified_query
│   ├── 09_guardrails/       # dedicated warehouse, resource monitor, audit log
│   └── 10_agent/            # CREATE AGENT: orchestrates analyst + search tools
├── streaming/
│   ├── schemas.py                              # shared Pydantic contracts (trades/bars/symbols/news)
│   ├── alpaca_stream_producer.py               # live feed (tenacity retries, structured logging, DLQ)
│   ├── generate_sample_data.py / replay_sample_data.py / generate_sample_news.py
│   ├── backfill_historical.py / backfill_news.py  # async/httpx batch backfill -> GCS -> Snowpipe
│   └── snowflake_kafka_connector.json
├── agent/
│   ├── cortex_client.py        # direct Cortex Analyst REST client (httpx + tenacity + Langfuse)
│   ├── cortex_agent_client.py  # Cortex Agent REST client (routes analyst vs. search per question)
│   ├── mcp_server.py           # FastMCP server exposing both clients + a guardrail query as tools
│   └── schemas.py
├── snowpark/
│   └── train_anomaly_model.py  # IsolationForest -> ONNX -> Snowflake Model Registry
├── ui/
│   └── streamlit_app.py        # Streamlit-in-Snowflake chat UI over the Cortex Agent
├── api/
│   └── main.py                 # FastAPI HTTP layer over the same clients
├── dbt/
│   ├── models/
│   │   ├── staging/     # 1:1 views over Silver (trades, bars, symbols)
│   │   └── marts/       # Gold star schema (dim_symbols, dim_date, fct_trades, fct_bars)
│   └── tests/assert_bar_ohlc_consistency.sql
├── semantic_layer/
│   ├── semantic_model.yaml   # Cortex Analyst YAML (richer custom metrics: period_return, volatility)
│   └── semantic_view.sql     # native Semantic View (what Cortex Agents/MCP actually query)
├── requirements.txt
└── docs/
    └── PORTFOLIO_BRIEF.md   # full reasoning history, for writeups/resume
```

## Setup order

1. Run `sql/02_bronze` to create the raw tables.
2. Set up the live/offline streaming path — follow
   [`streaming/README.md`](streaming/README.md) (start with the offline
   sample replay, no Alpaca account needed, then switch to the live feed).
   Run `streaming/generate_sample_news.py` (or `backfill_news.py` with a
   live Alpaca key) for the document corpus.
3. Run `sql/03_silver` for Streams+Tasks, and `sql/04_documents` for the news
   Bronze/Silver tables and the Cortex Search Service.
4. `cd dbt && dbt run` to build the Gold star schema from Silver (edit
   `profiles.yml.example` → `~/.dbt/profiles.yml` with your account first).
5. Run `sql/07_governance` (roles, Row Access Policy) and `sql/09_guardrails`
   (dedicated warehouse, Resource Monitor, audit log) — do this before
   opening anything up to real users, not after.
6. Run `semantic_layer/semantic_view.sql`, then `sql/10_agent/cortex_agent.sql`
   to create the multi-tool Cortex Agent.
7. Ask a question via Snowsight, [`agent/cortex_client.py`](agent/cortex_client.py)
   (direct Analyst), [`agent/cortex_agent_client.py`](agent/cortex_agent_client.py)
   (routed agent), `agent/mcp_server.py` (as MCP tools), the Streamlit app in
   `ui/`, or the FastAPI service in `api/` — all five go through the same
   governed path.
8. Run `dbt test` periodically, check the `suspect_bars_today` query, and
   consider training `snowpark/train_anomaly_model.py` once there's enough
   real bar history to make a learned threshold worthwhile.

## Status

Scaffolded and structurally complete, but **not yet run against live infra**
end-to-end — no live Snowflake account, Kafka broker, GCS bucket, or Langfuse
project has been connected yet (in progress). What has been verified locally,
without needing any of that: every Python file compiles and imports cleanly;
the offline sample generators (bars/trades/symbols/news) run and produce
schema-correct, timezone-correct output validated against `schemas.py`; the
DLQ routing logic was verified with deliberately malformed rows (which also
caught and fixed a real Pydantic field-ordering bug); and
`snowpark/train_anomaly_model.py` actually trains and exports a working ONNX
model against the sample bar data (which also caught and fixed a real
`skl2onnx` opset-version bug). The SQL (`CREATE SEMANTIC VIEW`, `CREATE AGENT`,
Cortex Search) is written to current documented syntax but hasn't been
executed against a real account yet — that's the next honest milestone, not
a claim already made.
