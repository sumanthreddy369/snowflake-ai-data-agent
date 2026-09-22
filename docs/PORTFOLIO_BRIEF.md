# Project: Snowflake AI Data Agent — Real-Time Market Data Pipeline with a Governed, No-Code AI Analyst

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
   at the Gold tables through that semantic model. No custom code here by
   design — the differentiator in this project is what feeds the agent, not
   the agent itself.
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
for full market coverage.

## Tech stack, in full

Snowflake (Snowpipe, Snowpipe Streaming, Streams & Tasks, Row Access
Policies, RBAC, Cortex Analyst), dbt, Apache Kafka (Kafka Connect Snowflake
Sink connector), Python (`kafka-python`, `websockets`), Alpaca Markets API.

## Current status — honestly

Scaffolded and pushed: 28 files, 8 commits, public at
https://github.com/sumanthreddy369/snowflake-ai-data-agent. What's actually
been verified: the offline sample-data generator runs and produces
schema-correct output (checked in-session), and the replay script's CSV
parsing/sorting logic was sanity-checked against that output. What has
**not** been run yet: no live Snowflake account, no live Kafka broker, and no
live Alpaca connection have been exercised end-to-end — the SQL and dbt
models are structurally complete and internally consistent (dbt's built-in
`unique`/`not_null`/`relationships` tests cover the Gold schema), but that's
the only automated test coverage that exists right now. There's no pytest
suite and no CI, unlike Project 2 — that's a clear gap worth closing before
claiming this is "production-tested," and it's next on the list.

## What to ask ChatGPT for, using this brief

- A polished case-study write-up (problem → approach → architecture → result)
- 2–3 resume bullets that lead with the *governance/validation* angle, not just "built a pipeline"
- A LinkedIn post summarizing the project and the reasoning behind each pivot
- A STAR-format interview answer for "tell me about a project you're proud of"

Let me know if you'd rather I draft the actual resume bullets / LinkedIn post
myself instead of routing through ChatGPT, since I already have all this
context.
