# AGENTS.md

Instructions for AI coding agents working in this repository.

## Project overview

A Snowflake-based pipeline that ingests real-time U.S. equities trades,
minute bars, and financial news, transforms them into a governed star schema
and a document search index, and exposes both to an AI agent through five
entry points (direct Cortex Analyst, a multi-tool Cortex Agent, an MCP
server, a Streamlit UI, a FastAPI service). See [README.md](README.md) for
the full architecture and [docs/PORTFOLIO_BRIEF.md](docs/PORTFOLIO_BRIEF.md)
for the reasoning history behind design decisions. Nothing in this repo has
been run against a live Snowflake account yet — treat every SQL file as
unverified against real infrastructure until told otherwise.

## Structure map

See [README.md](README.md#repository-structure) for the full annotated tree.
In short: `sql/NN_stage/` is numbered by pipeline order, `streaming/` is
ingestion-time Python, `agent/` is query-time Python, `dbt/` is the Silver→Gold
transformation, `semantic_layer/` defines what the agent can answer,
`snowpark/`, `ui/`, and `api/` are each a single-purpose add-on.

## Build, test, lint

- Install deps: `pip install -r requirements.txt`
- dbt: `cd dbt && dbt run` / `dbt test`
- No automated Python test suite exists yet — verification during
  development has been `python -m py_compile <file>` plus running scripts
  directly against `streaming/data/sample_*.csv`. If you add tests, they are
  the first ones in the repo; there's no existing suite to match, only the
  conventions below.
- **No linter or formatter is configured** — no `pyproject.toml`, `ruff.toml`,
  `.flake8`, or `Makefile` exists. Don't invent a config file speculatively;
  if the user asks for one, that's a real request, not something to assume.

## Code conventions actually used in this repo

- **Python 3.10+ union syntax** (`str | None`), not `Optional[str]`.
- **Pydantic v2 models for every data contract** — `streaming/schemas.py` for
  ingestion-time records, `agent/schemas.py` for query-time request/response
  shapes. These are two separate modules named `schemas.py` in different
  directories; don't assume importing `schemas` gets you both (see
  `docs/restructure-proposal.md` for the risk this creates).
- **Cross-field validation is a `model_validator(mode="after")`, not a
  `field_validator`** on one field checking another — Pydantic validates
  fields in declaration order, so a `field_validator` on a later-declared
  field can see an earlier one, but not the reverse. This bit the original
  `BarRecord.high` vs `low` check (see `streaming/schemas.py`'s comment);
  don't reintroduce that bug elsewhere.
- **Module-level `logging.basicConfig` + `logger = logging.getLogger("name")`**
  in every script, not bare `print()`. Structured-ish format strings
  (`"%(asctime)s %(levelname)s %(message)s"`), one exception in
  `alpaca_stream_producer.py` which uses a JSON-shaped format string.
- **`tenacity` for every outbound network call that can transiently fail**
  (Kafka producer sends are not retried this way; REST calls and the
  websocket connection are). Use `wait_exponential` + `stop_after_attempt`,
  matching the existing calls' parameters unless there's a specific reason
  to differ.
- **Every script is a CLI**: `argparse.ArgumentParser(description=__doc__)`,
  a `main()` function, `if __name__ == "__main__": main()`. Module docstrings
  explain purpose, why a design choice was made, and required env vars —
  they carry real information, not boilerplate.
- **SQL**: idempotent DDL (`CREATE ... IF NOT EXISTS` or `CREATE OR REPLACE`),
  `ALL_CAPS` for Snowflake object names, `snake_case` for columns, comments
  that explain *why* a choice was made (e.g. why Bronze is permissively
  typed, why a Row Access Policy instead of masking) rather than restating
  the SQL.
- **dbt**: staging models are thin 1:1 `select` statements from
  `{{ source(...) }}`; all real logic (window functions, derived flags)
  lives in `marts/`. Generic tests go in `schema.yml`; cross-column business
  rules that need a `WHERE` clause returning failing rows go in
  `tests/*.sql` as singular tests.

## Do

- Read the actual file before describing or changing it — several things in
  this repo look similar across directories (two `schemas.py` files, two
  `cortex_client`-style modules) and it's easy to conflate them.
- Keep the sample-data generators (`generate_sample_data.py`,
  `generate_sample_news.py`) runnable with zero external accounts — that's
  their entire purpose.
- Preserve the "flag, don't drop" pattern for data-quality issues that might
  be real (e.g. `is_suspect`) vs. the "reject and DLQ" pattern for messages
  that are definitely malformed (schema validation failures). These are
  different guardrails for different kinds of problems; don't merge them.
- When touching governance (`sql/07_governance`, `sql/09_guardrails`), keep
  the policy in the database, not in application code — every client in
  `agent/`, `ui/`, `api/` is meant to inherit access rules, not enforce them.

## Don't

- Don't rename `MARKET_AGENT` or restructure `sql/` folder numbering without
  flagging it — the numbering has a known gap and inconsistency (see
  `docs/restructure-proposal.md`); fixing it is a real, separate task, not
  something to do incidentally while working on something else.
- Don't add a `search_market_news` tool to `mcp_server.py` to match its
  docstring without confirming that's actually wanted — the docstring may be
  the thing that's wrong, not the code (see `docs/restructure-proposal.md`).
- Don't claim something works because the SQL "looks right" — until this
  repo has been run against live Snowflake, treat every SQL file as
  unverified and say so.
- Don't add a testing framework, linter, or CI config speculatively; these
  are known gaps (see README's Feature status), not silent assumptions to
  fill in.
