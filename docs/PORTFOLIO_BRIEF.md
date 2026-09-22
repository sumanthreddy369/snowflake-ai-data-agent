# Portfolio Brief: Snowflake AI Data Agent

Paste this whole file into ChatGPT (or any assistant) to get help turning it into a
resume bullet, LinkedIn post, or case-study write-up. It's the full context and
reasoning behind the project, not just the finished code.

## The one-line pitch

"I built an AI data agent on Snowflake that answers plain-English questions over
real-time stock market data — proving I can make raw, messy, live data accurate
and understandable to an AI agent, not just move it through a pipeline."

A second, separate project (Databricks + healthcare data) is being built in
parallel to show the same skill across a second stack and industry.

## Why this project exists

The goal was never "build a pipeline" — pipelines are commodity. The proof point
is: can messy/raw/live data be transformed so that an AI agent gives *correct*
answers to business questions, with a human able to verify every answer? That's
why the workflow has an explicit Validate step and a Governance step — most
portfolio pipelines skip both.

## Domain decisions, and why (in the order they were made)

1. **Started with retail** (orders/customers/products) as a generic placeholder.
2. **Switched to bank card transactions** (customers/merchants/transactions,
   with a fraud flag) — finance/banking is one of the largest DE/DA hiring
   verticals, and it gave the Governance step a real reason to exist (masking
   email/SSN mirrors PCI/GLBA-style controls) instead of being decorative.
3. **Added a real-time ingestion path**: real bank transaction feeds are never
   public (regulatory reality, not a data-availability gap), so the standard
   industry workaround is replaying a large realistic *synthetic* dataset
   (IBM's ~24M-row synthetic credit card transactions dataset) through Kafka
   into Snowflake's Kafka Connector running in Snowpipe Streaming mode —
   exactly how banks load-test fraud pipelines before touching live data.
4. **Pivoted to real-time stock market data (current, final domain)** — wanted
   genuinely *real* data, not synthetic, with rich variables and true
   real-time behavior. Real transaction-level bank data still isn't public,
   but live market data is: free, unauthenticated feeds (Alpaca's IEX feed)
   give real trade/quote/OHLCV data, which is literally what trading desks,
   brokerages, and robo-advisors run in production. This also raises the
   technical bar — real market-hours/timezone/corporate-action handling
   instead of a static replay — and stays inside the same finance vertical
   recruiters recognize.

The companion Databricks project intentionally stays on **healthcare**
(clinical notes + streaming vitals via Synthea, optionally MIMIC-IV later) to
diversify the portfolio across two regulated industries and to showcase
Databricks' actual differentiators (unstructured data, native streaming, Delta
Live Tables) instead of repeating the finance story twice.

## The 8-step workflow (what each stage actually does)

| Step | What happens | Tool |
|---|---|---|
| 1. Ingest | Real-time market data lands automatically | Alpaca websocket feed → Kafka → Snowpipe Streaming |
| 2. Bronze | Raw trades/quotes land untouched | Snowflake raw tables |
| 3. Silver | Clean, dedupe, standardize (e.g. corporate-action adjustments) | Streams + Tasks |
| 4. Gold | Business-ready star schema (price/volume/return facts) | dbt |
| 5. Semantic Layer | Define what "return," "volatility," "volume" mean | Cortex Analyst YAML |
| 6. Agent | Ask questions in plain English | Cortex Analyst |
| 7. Governance | Control who/what can access data | RBAC + Data Masking |
| 8. Validate | Check the agent's answers are correct | Manual SQL comparison |

## Architecture reasoning worth quoting

- **Snowpipe (batch) vs. Snowpipe Streaming (Kafka) vs. Databricks Structured
  Streaming**: Snowflake bolts real-time on as a Kafka Connector sitting
  outside the warehouse; Databricks treats streaming as a native execution
  mode of the same engine that runs batch. Both reach "real-time," but the
  underlying architecture — and how much you configure vs. code — is
  genuinely different. This contrast is deliberate, to demonstrate range
  across both lakehouse philosophies.
- **Governance is not decorative**: the `ANALYST_AGENT` role that Cortex
  Analyst queries as never receives the `PII_UNMASKED` role — the AI agent
  should never see raw sensitive fields, only aggregate/derived ones.
- **Validation is a discipline, not a one-off**: every `verified_query` in the
  semantic model has a hand-written SQL twin in `sql/08_validation/`, so any
  answer the agent gives can be independently checked.

## Repo

https://github.com/sumanthreddy369/snowflake-ai-data-agent — currently modeling
real-time equities trades/bars (Alpaca feed), after two earlier pivots (retail
→ bank transactions → market data) each documented in the commit history.

## What to ask ChatGPT for, using this brief

- A polished case-study write-up (problem → approach → architecture → result)
- 2–3 resume bullets that lead with the *validation/governance* angle, not just "built a pipeline"
- A LinkedIn post summarizing the project and the reasoning behind each pivot
- A STAR-format interview answer for "tell me about a project you're proud of"
