# Project: Snowflake AI Data Agent — Real-Time Market Data + RAG Pipeline with a Governed, Multi-Tool AI Agent

Paste this whole file into ChatGPT (or any assistant) to get help turning it into
a resume bullet, LinkedIn post, or case-study write-up. It's the full context
and reasoning behind the project, not just the finished code.

**Context:** This is Project 1 of a two-part portfolio series. Project 2
(`databricks-agentic-de`) takes the harder path — a real-time healthcare
pipeline with a custom-coded AI agent built on the Anthropic API, because
Databricks' own no-code agent tool (Genie) can't be built or demoed without a
live paid workspace. Project 1 deliberately takes the other real path: use a
managed, no-code AI product (Snowflake Cortex Analyst) well — which means the
proof point isn't "I can write an agent," it's "I can take genuinely messy,
live data and make it accurate and governed enough that a vendor's AI product
gives correct, safe answers." Configuring and governing a managed AI product
correctly is its own real skill, distinct from building one from scratch, and
most portfolio projects that use a no-code tool don't take the Validate or
Governance steps seriously — this one does.

## The thesis

Real companies want AI agents to reduce manual DE/DA work, but the actual
bottleneck is never the agent — it's whether the data underneath it can be
trusted. This project proves that concretely: an AI agent (Cortex Analyst)
answers plain-English questions over real-time market data, and every answer
it can give is provably either (a) governed — the agent's role is
architecturally incapable of seeing real-time prices it isn't entitled to, or
(b) checkable — every business-metric definition the agent uses has a
hand-written SQL twin that independently verifies it.

## Domain, and the reasoning trail behind it

The domain went through two earlier pivots before landing on the final one,
each driven by a specific flaw in the previous choice — worth keeping in a
write-up because it shows engineering judgment, not just a finished result:

1. **Started with retail** (orders/customers/products) as a generic placeholder.
2. **Switched to bank card transactions** (customers/merchants, fraud flag) —
   finance/banking is one of the largest DE/DA hiring verticals, and it gave
   the Governance step a real reason to exist (masking email/SSN, mirroring
   PCI/GLBA-style controls) instead of being decorative. Real-time was
   simulated by replaying IBM's ~24M-row synthetic credit-card-transactions
   dataset through Kafka — the actual industry pattern for load-testing fraud
   pipelines before touching live data, since real transaction feeds are
   never public.
3. **Pivoted to real-time U.S. equities market data (final domain)** — even a
   large synthetic dataset is still synthetic. Alpaca's free IEX feed gives
   genuinely real trade/quote/OHLCV data with no compliance wall, and it
   raises the technical bar in ways synthetic data can't: market hours,
   timezones, and true streaming volume, while staying in the same
   recognizable finance vertical.

## The 8-step pipeline and the tech behind each step

1. **Ingest** — two paths, matched to two different data shapes: a live
   Alpaca websocket feed (trades + minute bars) published to Kafka topics via
   a Python producer, consumed into Snowflake through the Kafka Connector
   running in **Snowpipe Streaming** mode (row-level, seconds latency); and
   file-based **Snowpipe** for slower-changing reference data (the symbol
   table, historical bar backfills) that doesn't need to be real-time.
2. **Bronze** — raw Snowflake tables, deliberately permissively typed
   (`VARCHAR` everywhere) so a malformed row is never rejected at this layer
   — that's Silver's job.
3. **Silver** — Streams + Tasks: a Stream tracks what changed in Bronze since
   it was last consumed, and a scheduled Task (`WHEN
   SYSTEM$STREAM_HAS_DATA(...)`, so it never runs on empty data) casts types,
   dedupes by natural key via `QUALIFY ROW_NUMBER()`, and MERGEs into Silver.
4. **Gold** — a dbt-built star schema (`dim_symbols`, `dim_date`,
   `fct_trades`, `fct_bars`), where `fct_bars` computes a genuine derived
   metric in SQL, not just a passthrough: a trailing 30-bar rolling
   volatility via a window function (`STDDEV(...) OVER (PARTITION BY symbol
   ORDER BY bar_ts ROWS BETWEEN 29 PRECEDING AND CURRENT ROW)`).
5. **Semantic Layer** — a Cortex Analyst YAML file that gives ambiguous
   financial terms one enforced definition: "return" is last-close-vs-first-
   open over the filtered window, never an average of per-bar returns;
   "volatility" is the average of the precomputed rolling stddev, never a
   single global stddev that would blend calm and turbulent periods together;
   "VWAP" is volume-weighted, never a plain average of price.
6. **Agent** — Cortex Analyst, Snowflake's managed NL-to-SQL product, pointed
   at the Gold tables through that semantic model. No custom agent logic by
   design — the differentiator in this project is what feeds the agent, not
   the agent itself — but every question sent to it optionally goes through
   `agent/cortex_client.py`, a thin `httpx` wrapper that traces the call
   through Langfuse (question, latency, generated SQL), giving this
   no-code agent the same observability discipline as a hand-coded one.
7. **Governance** — market data carries no customer PII, so instead of
   masking, governance here models real market-data *licensing*: a **Row
   Access Policy** means any role without the `REALTIME_DESK` entitlement —
   including `ANALYST_AGENT`, the role Cortex Analyst queries as — only ever
   sees trades/bars that are 15+ minutes old. This mirrors exactly how real
   exchanges and data vendors gate delayed vs. real-time quote entitlements,
   so the AI agent is architecturally incapable of leaking a real-time price
   it isn't licensed to show.
8. **Validate** — every `verified_query` in the semantic model has a
   hand-written SQL twin in `sql/08_validation/`, so any answer the agent
   gives can be independently checked rather than trusted on faith.

## Beyond the 8 steps: RAG, a multi-tool agent, MCP, and a learned guardrail

The original 8-step pipeline proved the thesis with structured data alone.
Extending it added the pieces that turn "an agent answering questions" into
"an agent that knows when it needs a second tool" — matching how real
enterprise data-intelligence stacks are actually built, not just the minimum
needed to demo one question type:

- **Cortex Search + a document source** — trades/bars have no unstructured
  data, so RAG had no reason to exist until a real document source was added:
  Alpaca's News API (same account, no new vendor), pulled concurrently
  (`backfill_news.py`) into a `RAW_NEWS` → `SILVER.NEWS` pipeline that mirrors
  the structured branch's own Bronze/Silver pattern, then indexed by a Cortex
  Search Service with citations (`url`, `source`, `published_at` as
  attributes) so "what's happening with AAPL" comes back with a real link,
  not an unsourced claim.
- **A native Semantic View, alongside the YAML** — Cortex Agents and
  Snowflake's managed MCP server only consume the newer `CREATE SEMANTIC VIEW`
  object, not the YAML semantic model file the direct Cortex Analyst client
  uses. Rather than force every metric into one format, both exist: the YAML
  carries the metrics that need window-function logic (`period_return`,
  `volatility`) too custom for a plain semantic-view `METRIC`, while the
  Semantic View covers the standard aggregations Cortex Agents actually query.
- **A Cortex Agent that routes between two tools** — `sql/10_agent/cortex_agent.sql`
  defines one agent with an `analyst` tool (Semantic View) and a `search`
  tool (Cortex Search over news), with orchestration instructions telling it
  when to use one, the other, or both ("why did AAPL drop today" needs the
  price move *and* a news explanation). This is the actual "agent" in the
  agentic sense — a decision about which tool to call — where Cortex Analyst
  alone was always a single fixed capability.
- **MCP, so the agent is a callable tool, not just a chat endpoint** — a
  standalone FastMCP server (`agent/mcp_server.py`) exposes the agent, the
  direct analyst client, and a guardrail-monitoring query as MCP tools any
  MCP-aware client can call. Deliberately not Snowflake's own managed MCP
  server, which is a Native Apps feature requiring the whole project to be
  packaged as a Snowflake Native App — a heavier lift than the value it adds
  here, so this is an honest, simpler substitute that wraps the same governed
  clients rather than a claim of using Snowflake's specific offering.
- **A learned replacement for a guessed threshold** — the circuit-breaker
  guardrail (`is_suspect`, a fixed ">10% one-minute move" rule) is exactly
  the kind of thing that should eventually be a model instead of a guess:
  `snowpark/train_anomaly_model.py` trains an IsolationForest on bar returns,
  exports it to ONNX, and documents registering it to Snowflake's Model
  Registry so it runs as a plain SQL-callable function — no external
  model-serving infrastructure. Training and export were actually run
  locally against the sample data (see Status below); registration is
  written but not yet executed against a live account.
- **A UI and an HTTP API, not just Snowsight** — `ui/streamlit_app.py`
  (Streamlit-in-Snowflake) is the demoable chat interface for screenshots and
  a live walkthrough; `api/main.py` (FastAPI) is the "when an external
  service layer is beneficial" option for anything outside Snowflake that
  needs to call the agent. Both are thin pass-throughs with no separate
  access logic — they inherit the same Row Access Policy and role
  restrictions as every other entry point, because governance lives in the
  database, not duplicated per client.
- **Dynamic Tables, shown alongside Streams+Tasks** — `sql/03_silver/dynamic_tables_alternative.sql`
  reimplements the simplest Silver table declaratively, explicitly labeled as
  an alternative pattern rather than a replacement, to show both the
  "I understand CDC mechanics" version and the "I know the newer, less-code
  way" version exist and when each is the better tool.

## Guardrails — the part that separates this from a toy pipeline

Real companies running AI agents over live data don't trust the agent; they
constrain the blast radius so a bad answer or a bad query can't do damage.
This project implements the concrete version of that, not just the concept:

- **Dead-letter queue** — a malformed trade/bar message doesn't get logged
  and dropped, it gets routed to a `market-data-dlq` Kafka topic so it stays
  inspectable. Building this exposed a real bug: an early OHLC sanity check
  was a per-field Pydantic validator that silently never fired, because
  Pydantic validates fields in declaration order and `low` wasn't parsed yet
  when `high` was checked against it. Fixed with a model-level validator that
  sees every field regardless of order — the kind of subtle correctness bug
  that only shows up when you actually test the failure path, not just the
  happy path.
- **Hard data-quality gate** — `dbt test` fails the build if any Gold row has
  `high < low`, a non-positive price, or negative volume. Not a warning, a
  build failure.
- **Circuit-breaker flag, not a filter** — a >10% one-minute move gets an
  `is_suspect` flag in `fct_bars` rather than being silently dropped or
  silently trusted. A real earnings move and a bad tick look identical to a
  naive filter; flagging both for review is the honest answer, and a
  monitoring query (`suspect_bars_today`) surfaces them.
- **Blast-radius isolation** — the agent's role queries through a dedicated
  warehouse (`ANALYST_WH`) with a 30-second statement timeout and its own
  Resource Monitor, so a runaway or malicious NL-generated query can only ever
  burn that warehouse's capped budget, never contend with ingestion/dbt
  compute or blow through the account's credits.
- **Append-only audit trail** — every question asked through
  `agent/cortex_client.py` and the SQL Cortex Analyst generated for it gets
  written to `MARKET_AGENT.GOVERNANCE.AGENT_QUERY_AUDIT_LOG`. The agent's role
  can `INSERT` into that table but never `UPDATE`/`DELETE` — it can't quietly
  edit its own history. If the audit write itself fails, that's logged at
  `ERROR` level but never allowed to break the user-facing answer — a broken
  audit path shouldn't punish the user, but a silent audit gap is its own
  incident, which is why it's loud instead of swallowed.
- **Row Access Policy** (covered under Governance above) is the guardrail that
  matters most: the agent's role is architecturally incapable of seeing a
  real-time price it isn't licensed to show, regardless of what question is
  asked or how it's phrased.

## Dataset

Two sources, matched to the same Bronze schema so nothing downstream cares
which one is running: (1) **live** — Alpaca's free IEX websocket feed,
requiring a free Alpaca account and only usable during US market hours; (2)
**offline fallback** — a small (~10k-row) synthetic random-walk generator
(`streaming/generate_sample_data.py`) producing trades/bars/symbols for 5
tickers across one simulated trading day, checked into the repo so the
pipeline can be exercised with no external account and at any time of day.
This is an honest stand-in, not a claim of real historical data — the
natural next step is backfilling real historical bars via Alpaca's REST API,
or upgrading from the free IEX feed to the paid SIP (consolidated tape) feed
for full market coverage. The same live/offline pattern applies to the news
corpus for RAG: `generate_sample_news.py` for a synthetic stand-in, or
`backfill_news.py` for real headlines from Alpaca's News API.

## Tech stack, in full

Snowflake (Snowpipe, Snowpipe Streaming, Streams & Tasks, Dynamic Tables, Row
Access Policies, RBAC, Resource Monitors, Cortex Analyst, Cortex Search,
Cortex Agents, native Semantic Views), dbt, Apache Kafka (Kafka Connect
Snowflake Sink connector), **Google Cloud Storage** (deliberately chosen over
the more common S3 pattern, to diversify cloud experience across the
portfolio), MCP (FastMCP), Streamlit, FastAPI, scikit-learn + ONNX
(`skl2onnx`) + Snowflake Model Registry, Python (`kafka-python`,
`websockets`, `httpx`, `asyncio`, `pydantic`, `tenacity`), Langfuse (tracing
every Cortex Analyst / Cortex Agent call), Alpaca Markets API (market data
and news, same account for both).

Reused deliberately from other projects in this portfolio, for stack
consistency: Pydantic (typed contracts for every record the pipeline moves —
`streaming/schemas.py`, `agent/schemas.py`), `tenacity` (retry with backoff on
the live websocket connection and outbound API calls), `httpx` + `asyncio`
(concurrent per-symbol historical/news backfill), structured logging, and
Langfuse (wrapping every LLM-adjacent call in this project).

## Current status — honestly

Scaffolded and pushed, public at
https://github.com/sumanthreddy369/snowflake-ai-data-agent. What's actually
been verified, all without needing live infra: every Python file across
`streaming/`, `agent/`, `ui/`, `api/`, and `snowpark/` compiles and imports
cleanly; the offline sample generators (bars/trades/symbols/news) run and
produce timezone-correct (UTC), schema-valid output; the DLQ routing logic
was verified with deliberately malformed rows, which also caught and fixed a
real Pydantic field-ordering bug (a per-field validator that silently never
fired because Pydantic validates fields in declaration order);
`snowpark/train_anomaly_model.py` actually trains an IsolationForest and
exports a working ONNX file against the sample data, which also caught and
fixed a real `skl2onnx` opset-version bug. What has **not** been run yet: no
live Snowflake account, Kafka broker, GCS bucket, Alpaca connection, or
Langfuse project has been exercised end-to-end, so the `CREATE SEMANTIC VIEW`,
`CREATE CORTEX SEARCH SERVICE`, and `CREATE AGENT` statements are written to
current documented syntax but unexecuted against a real account — that's
the next honest milestone. There's also no pytest suite or CI yet, unlike
Project 2 — a clear gap worth closing once the live pipeline is confirmed
working, so tests are written against real behavior rather than assumptions.

## What to ask ChatGPT for, using this brief

- A polished case-study write-up (problem → approach → architecture → result)
- 2–3 resume bullets that lead with the *governance/validation* angle, not just "built a pipeline"
- A LinkedIn post summarizing the project and the reasoning behind each pivot
- A STAR-format interview answer for "tell me about a project you're proud of"

Let me know if you'd rather I draft the actual resume bullets / LinkedIn post
myself instead of routing through ChatGPT, since I already have all this
context.
