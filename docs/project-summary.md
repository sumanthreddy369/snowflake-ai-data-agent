# Project summary (with verifiable numbers)

A short, resume-style summary of what this project has actually achieved.
Every number links to where it was produced, so each claim can be checked.

## Snowflake AI Data Agent: Governed Real-Time Market Data Pipeline

**Snowflake · dbt · Dagster · Kafka · Terraform · OpenTelemetry · Prometheus · Grafana · GitHub Actions**

- Built a medallion pipeline on Snowflake (Bronze → Silver → Gold) for
  equities market data: trades, minute bars, symbols and news ingested via
  Kafka/Snowpipe, merged incrementally with Streams + Tasks, and modelled
  into a star schema with dbt — **19/19 models and tests passing**, with
  **9,795 rows reconciled 100%** across layers.
- Implemented row-level governance for licensed real-time data: a row access
  policy enforcing a 15-minute delay for non-entitled roles, verified across
  **12 role × secondary-role × timezone combinations**; found and fixed a
  **secondary-role privilege leak** that exposed real-time prices to the AI
  agent's role.
- First live deployment surfaced and fixed **6 production defects** (invalid
  column defaults, missing warehouse grants, a dbt spine error, a monitoring
  false positive); the full build ran for **0.49 credits** under a
  110-credit resource-monitor cap.
- Wired orchestration and observability: a **21-asset Dagster graph**
  deriving deploy order from dependencies, **Terraform** for GCP and
  Snowflake infrastructure, **11 automated CI checks**, and OpenTelemetry →
  Prometheus/Grafana with **4 alert rules**; replay tests matched app metrics
  to Kafka offsets exactly (**15,900 trades, 4,001 bars**) and caught a
  validation gap that let nameless records through (**3/3 rejected after
  the fix**).

Agent-focused alternative for the last bullet:

- Built a guardrailed text-to-SQL agent on a local LLM (qwen3:14b via Ollama)
  over the governed Gold schema: an AST-based SQL guardrail (**23 unit
  tests**) allows only single read-only queries on allow-listed tables, and
  every query runs under the agent's restricted role and is audit-logged.
  Raised accuracy on a 15-question reference eval from **53% to 87%**
  through output caps, robust parsing and data grounding, with **8/8 attack
  prompts blocked, 0 unsafe executions**, and **2.3 s median latency**.

## Evidence

| Number | Where it comes from |
|---|---|
| 19/19 dbt, 9,795 rows, 0.49 credits, 6 defects, 12-combination governance matrix | [snowflake-results.md](snowflake-results.md) |
| 15,900 / 4,001 Kafka offsets, 4 alert rules, 3/3 after fix | [stack-results.md](stack-results.md) |
| 21 Dagster assets, 11 CI checks | `orchestration/`, `.github/workflows/ci.yml` |
| 158 problems, 18 SQL pairs, 3 glue agents | `knowledge/problem_catalog.yaml`, [glue-and-guardrails.md](glue-and-guardrails.md) |
| 53% → 87% accuracy, 8/8 attacks blocked, 0 unsafe, 2.3 s median, 23 unit tests | [agent-eval-results.md](agent-eval-results.md), [snowflake-results.md §8](snowflake-results.md) |

## Not claimed (yet)

- Real market data or real-time production: runs so far used the sample
  dataset; the live Alpaca stream into Snowflake hasn't run.
- Snowflake Cortex: unavailable on trial accounts; the working agent uses a
  local model instead.
- Accuracy on a large or real-user question set: the eval has 15 questions
  plus 8 attacks on one sample trading day.
