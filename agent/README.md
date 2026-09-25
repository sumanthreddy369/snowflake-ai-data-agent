# Agent client (Step 6, instrumented)

Cortex Analyst itself needs no code — Snowsight's chat UI calls it directly.
This folder exists for one reason: to make every question asked of the agent
observable the same way an LLM call in a hand-coded agent would be, using the
same Langfuse-based observability pattern as this project's other work.

`cortex_client.py` is a thin `httpx` wrapper around the [Cortex Analyst REST
API](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst/rest-api),
decorated with Langfuse's `@observe(as_type="generation")` so every call
records the question, latency, and the SQL Cortex Analyst generated. Retries
transient failures via `tenacity`; request/response shapes are Pydantic
models in `schemas.py`.

**This is not where governance happens.** The client authenticates with a PAT
scoped to the `ANALYST_AGENT` role, and it's the Row Access Policy on that
role (`sql/07_governance/rbac_and_masking.sql`) — not anything in this
code — that guarantees it can never see a real-time (<15-minute-old) price.
That's deliberate: governance belongs in the database, not in application code
that could have a bug or be bypassed.

**Guardrails wired in here** (see `sql/09_guardrails/cost_and_access_guardrails.sql`
for the database side):
- Every question and its generated SQL is written to an append-only audit
  table (`MARKET_AGENT.GOVERNANCE.AGENT_QUERY_AUDIT_LOG`) after each call.
  `ANALYST_AGENT` can `INSERT` into it but never `UPDATE`/`DELETE` — the log
  can't be quietly edited by the same role it's recording.
- If the audit write itself fails, it's logged at `ERROR` level but never
  raised — a broken audit path shouldn't take down the user-facing answer,
  but a silent audit gap is its own incident, hence the loud log instead of a
  swallowed exception.
- The client connects through `ANALYST_WH`, a dedicated warehouse with a
  30-second statement timeout and its own Resource Monitor — a runaway or
  malicious query can only ever burn that warehouse's capped budget, never
  contend with ingestion/dbt compute or blow through the whole account's
  credits.

## Setup

```bash
pip install httpx pydantic tenacity langfuse
export SNOWFLAKE_ACCOUNT_HOST=xy12345.snowflakecomputing.com
export SNOWFLAKE_ACCOUNT=xy12345          # account identifier for the connector (audit log write)
export SNOWFLAKE_USER=<a user with the ANALYST_AGENT role>
export SNOWFLAKE_PAT=<a programmatic access token for that user>
export CORTEX_SEMANTIC_MODEL_FILE=@MARKET_AGENT.GOLD.SEMANTIC_MODELS/semantic_model.yaml
export SNOWFLAKE_WAREHOUSE=ANALYST_WH      # optional, this is already the default
export SNOWFLAKE_ROLE=ANALYST_AGENT        # optional, this is already the default
export LANGFUSE_PUBLIC_KEY=... LANGFUSE_SECRET_KEY=... LANGFUSE_HOST=...

python cortex_client.py "What was today's return for AAPL?"
```
