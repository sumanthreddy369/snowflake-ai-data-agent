# Study: a stage-gated, AI-assisted build of the data model, with a report at every stage

Plan of record: `docs/glue-and-guardrails.md`. This study is the detailed
workflow of its **Change glue** agent, applied to building a whole model.

Status: **study only — nothing here is built yet.** This document decides what
the agents need to be given, what each stage must produce, what each stage's
report contains, and how we'll know the agents work. Building starts after the
open decisions at the end are answered.

---

## 1. The goal in one paragraph

Give a set of AI agents a business goal ("analysts need to ask questions about
U.S. equities prices and news, with real-time prices only for entitled users")
plus access to the sources, and have them build the whole data model — ingestion,
Bronze, Silver, Gold star schema, semantic layer, governance, validation,
release — one stage at a time. After every stage the agents stop, write a report
(what they built, the evidence it works, what they checked, what's risky), and
wait for a human to approve before the next stage starts. Nothing reaches
production without passing every gate.

**We don't build agents from scratch, and we don't replace existing tools.**
The work inside each stage is done by an existing AI assistant (Claude, used
through the Anthropic SDK) driving the existing tools — Snowflake, dbt,
Dagster, Terraform, git. What this project builds is what companies build
around such assistants:

- **Glue** — the stage runner, the handoffs between stages, the question
  tracker, and the reports, so one run flows from requirements to production.
- **Guardrails** — the checks, least-privilege tools, DEV-only writes, and the
  human approval at each gate, so the assistant can't take an unsafe step.

The purpose is to **remove human work, not human judgement** (see
`docs/production-readiness.md` §0): people stop writing boilerplate DDL, dbt
scaffolding and checks by hand, and instead review a report and approve, once
per stage. The problem catalog (`knowledge/problem_catalog.yaml`) is the
checklist each stage is held to.

---

## 2. The stages

| # | Stage | Builds | Main question the report answers |
|---|---|---|---|
| 0 | Intake | Requirements brief | Do we agree on what's being built and how we'll judge it? |
| 1 | Source discovery and profiling | Source profile | What do the sources really contain — fields, volumes, keys, timestamps, quality? |
| 2 | Ingestion and contracts | Pydantic contracts, Kafka topics, Snowpipe config, Bronze tables | Is raw data landing completely, with bad messages quarantined? |
| 3 | Cleaning and conformance | Streams + Tasks, Silver tables | Is Silver deduplicated, typed and complete compared with Bronze? |
| 4 | Dimensional modeling | Gold star schema in dbt + tests | Is the grain right, are keys unique, do the facts answer the questions? |
| 5 | Semantic layer and search | Semantic view, YAML model, verified queries, Cortex Search | Can every business question be answered from the model? |
| 6 | Governance | Roles, grants, row access policy | Does each role see exactly what it should — tested, not assumed? |
| 7 | Validation and QA | Reconciliation, verified-query twins, agent evals | Do the numbers reconcile across layers and match hand-written SQL? |
| 8 | Release | Deploy plan, CI run, rollback plan | Is it safe to put in production, and how do we undo it? |
| 9 | Hand-off to operations | Monitors, alerts, runbooks | What do the alerts and checks watch, and what does "healthy" look like? |

---

## 3. What you need to give the agents

This is the part only you can supply. Without these the agents would be
guessing, and a confident guess is the most expensive kind of error here.

| # | Input | Example for this project | Used in stages |
|---|---|---|---|
| 1 | **Business questions** (10–30), each with what a correct answer looks like | "What was AAPL's return today?" → open-to-close % for the regular session | 0, 4, 5, 7 |
| 2 | **Sources**: API docs, sample files, connection details (credentials via environment variables, never in prompts) | Alpaca trades/bars/news API; `streaming/data/sample_*.csv` | 1, 2 |
| 3 | **Access rules**: who may see what | Real-time prices only for `REALTIME_DESK`; everyone else 15 minutes delayed | 6, 7 |
| 4 | **Freshness and volume targets** | Prices within 1 minute; news within 1 hour; ~8k trades/min peak | 2, 3, 9 |
| 5 | **Definitions and conventions**: metric definitions, naming, timezone rules | All timestamps UTC `TIMESTAMP_NTZ`; regular session 9:30–16:00 ET; `ALL_CAPS` objects | 0, 3, 4, 5 |
| 6 | **Environments and limits**: databases, warehouses, credit budget | DEV / TEST / PROD; `ANALYST_WH`; credit cap per run | 2–8 |
| 7 | **Approvers**: who signs off each gate | You for every gate at first | all |
| 8 | **Definition of done**: what must be true at the end | Every business question answered and matching its sql/08 twin; all governance tests pass | 7, 8 |

Stage 0's job is to turn these into a written brief, list anything missing or
contradictory, and refuse to continue until you've approved it.

---

## 4. Stage by stage: inputs, work, outputs, report, gate

Every stage follows the same shape:

```
inputs (your brief + previous stage outputs)
  → agent works in a git branch, using only its allowed tools
  → automatic checks run
  → stage report written
  → human approves / requests changes / stops
```

### Stage 0 — Intake
- **Agent does:** reads your inputs, restates each business question as a
  precise definition (metric, grain, filters, time window, timezone), lists
  gaps and contradictions.
- **Outputs:** `runs/<run>/00_requirements.yaml` (machine-readable brief).
- **Report:** the brief, open questions, assumptions it wants you to confirm.
- **Gate:** every question has a definition; every open question answered.

### Stage 1 — Source discovery and profiling
- **Agent does:** connects to each source (or sample files), infers fields and
  types, finds candidate keys, measures null rates, duplicates, value ranges,
  timestamp formats and timezones, arrival lateness, volume per minute.
- **Outputs:** source profile per source; draft field mapping to business
  questions.
- **Report:** per-source profile table; "questions we can't answer from these
  sources"; data-quality risks found. Catalog problems checked: A3, A7, A8, A9,
  K1–K3, K7, L2, L6.
- **Gate:** every business question maps to at least one source field.
- **Runs offline today** against `streaming/data/sample_*.csv`.

### Stage 2 — Ingestion and contracts
- **Agent does:** writes Pydantic contracts (model-level validators for
  cross-field rules, per AGENTS.md), Kafka topic + DLQ config, Snowpipe /
  Snowpipe Streaming config, Bronze DDL (permissive types, `SYSDATE()` load
  timestamps).
- **Outputs:** `streaming/schemas.py`-style contracts, connector config,
  `sql/02_bronze/*.sql`.
- **Report:** rows sent vs rows landed per source, DLQ count and top error
  types, end-to-end latency, replay test result. Catalog: B1–B5, C1–C5, I3, K2.
- **Gate:** landed = sent − DLQ (within tolerance); replay of sample data is
  idempotent.

### Stage 3 — Cleaning and conformance
- **Agent does:** Streams + Tasks (or Dynamic Tables) MERGEing Bronze → Silver
  with typing, dedupe on business keys, standardisation (upper-case symbols,
  UTC timestamps).
- **Outputs:** `sql/03_silver/*.sql`.
- **Report:** rows in vs rows out per table, rows rejected and why, null rate
  per cast column, duplicate keys removed, task run times vs schedule. Catalog:
  D1–D5, K5–K7, M1, M2, P10, P12, P13.
- **Gate:** reconciliation Bronze → Silver within tolerance; no task overlap.

### Stage 4 — Dimensional modeling
- **Agent does:** proposes the star schema (grain of every fact, conformed
  dimensions, keys, slowly changing dimension choice), then writes dbt models,
  `schema.yml` tests and singular tests.
- **Outputs:** `dbt/models/**`, ER diagram, design notes.
- **Report:** the model diagram, grain statement per fact, which business
  question each fact/dimension serves, dbt test results, row counts. Catalog:
  E1–E6, K10, L3–L5, P1, P14, plus the GOLD_GOLD schema bug (dbt schema naming).
- **Gate:** `dbt parse` + `dbt test` pass; every business question is
  answerable by a join path in the model. **This is the stage you'll most want
  to review by hand.**
- **Can be designed offline** from the stage 1 profile; building needs Snowflake.

### Stage 5 — Semantic layer and search
- **Agent does:** writes the semantic view and YAML model (metrics, dimensions,
  synonyms, verified queries), and the Cortex Search service for documents.
- **Outputs:** `semantic_layer/*`, `sql/04_documents/*`.
- **Report:** coverage table (each business question → metric → verified
  query), YAML-vs-semantic-view consistency check, search precision on a small
  labelled set. Catalog: F2–F5, F8, N4.
- **Gate:** 100% of business questions have a verified query; YAML and semantic
  view agree.

### Stage 6 — Governance
- **Agent does:** roles, grants (including FUTURE grants), row access policy
  attached by dbt post-hook, managed access where needed.
- **Outputs:** `sql/07_governance/*`, dbt post-hooks.
- **Report:** access matrix (role × object × visible rows), policy tests run as
  each role and under two session timezones, policy-attachment check after a
  dbt rebuild. Catalog: E4, G1–G5, K8, S1–S9.
- **Gate:** every access test passes; agent role is read-only on Gold only.

### Stage 7 — Validation and QA
- **Agent does:** runs cross-layer reconciliation, the sql/08 hand-written twin
  of every verified query, and the ANALYST agent eval set.
- **Outputs:** `sql/08_validation/*`, eval results.
- **Report:** a QA scorecard — reconciliation per layer, verified-query matches,
  agent answer accuracy, routing accuracy, citation rate, open defects. Catalog:
  F1–F9, M4, N1–N3, O2.
- **Gate:** definition of done (input 8) met.

### Stage 8 — Release
- **Agent does:** builds the deploy order, proves it on an empty database,
  writes the rollback plan (clones + SWAP), runs CI.
- **Outputs:** deploy plan, CI run, release notes.
- **Report:** what changes in production, deploy order, test results on a
  clone of production, rollback steps, who approved. Catalog: R1–R12.
- **Gate:** human approval is always required here, regardless of autonomy level.

### Stage 9 — Hand-off to operations
- **Agent does:** sets up Snowflake alerts, data metric functions, budgets,
  and the ops runbook entries.
- **Report:** what's monitored, thresholds, who gets paged, baseline numbers.
- **Gate:** every monitor fires correctly on an injected fault.

---

## 5. How the stages connect

The stages are one chain, not ten separate jobs. Five things tie them together.

### 5.1 Every stage hands over a structured package to the next

A stage doesn't finish with "done"; it finishes with a **handoff**: a
validated object listing exactly what the next stage needs. The orchestrator
checks the handoff before the next stage may start; the next agent starts by
reading every earlier handoff, not by rediscovering things.

| From → to | What is handed over |
|---|---|
| 0 → 1 | Business questions with precise definitions (metric, grain, filters, time window, timezone); access rules; targets |
| 1 → 2 | Per source: fields and types, candidate keys, timestamp format and timezone, volume per minute, quality risks; question → source-field map |
| 2 → 3 | Bronze tables and columns, load-timestamp column, DLQ location, observed lateness and duplicate rates |
| 3 → 4 | Silver tables with business keys, types, dedupe rule, standardisation rules, reconciliation numbers |
| 4 → 5 | Facts and dimensions with grain, keys, measure columns, join paths; question → table/column map |
| 5 → 6 | Semantic objects and search service the agent will query; which of them carry time-sensitive data |
| 6 → 7 | Roles, grants, policies, and the expected visibility per role (the test oracle for stage 7) |
| 7 → 8 | QA scorecard, open defects, the exact object list to release |
| 8 → 9 | What's now in production, baselines, rollback plan |

```python
class Handoff(BaseModel):
    run_id: str
    from_stage: int
    artifacts: list[str]            # files and Snowflake objects produced
    facts: dict[str, Any]           # what the next stage needs, stage-specific schema
    question_status: dict[str, str] # Q-id -> where it stands after this stage
    unresolved: list[str]           # carried forward, must be closed by a named stage
```

Each stage has its own `facts` schema (for example stage 1's is a list of
`SourceProfile` objects), so a missing key is caught by validation, not by the
next agent failing halfway.

### 5.2 Every business question is traced through every stage

Each question gets an ID at stage 0 (Q01, Q02, ...) and every stage records
what happened to it. Every report ends with the same tracker, so a gap shows up
at the stage where it appears, not at the end:

| Q | Definition (0) | Source fields (1) | Bronze/Silver (2–3) | Gold columns (4) | Metric / verified query (5) | Who can see it (6) | Test result (7) |
|---|---|---|---|---|---|---|---|
| Q01 AAPL return today | open→close %, regular session, UTC date | bars.o, bars.c, bars.t | RAW_BARS → SILVER.BARS | FCT_BARS.open/close/bar_ts | `todays_return_by_symbol` | delayed for ANALYST_AGENT | matches sql/08 twin |

### 5.3 Every stage connects to the real systems it works on — and proves it first

Each stage starts with a **preflight**: it connects to its systems with the
stage's own least-privilege role, runs a harmless check, and records the result
in its report. If preflight fails, the stage stops before doing any work.

| Stage | Connects to | Preflight check |
|---|---|---|
| 0 | Repo, your input files | Inputs present and parseable |
| 1 | Alpaca REST (or sample files), Snowflake DEV (read) | API clock call; `SELECT CURRENT_ROLE(), CURRENT_WAREHOUSE()` |
| 2 | Kafka, Kafka Connect, GCS bucket, Snowflake DEV | List topics; Connect status; list bucket; `SHOW SCHEMAS` |
| 3 | Snowflake DEV | Bronze tables exist and have rows |
| 4 | Snowflake DEV, dbt | `dbt debug`; Silver tables exist |
| 5 | Snowflake DEV (Cortex) | Gold tables exist; Cortex available in the region |
| 6 | Snowflake DEV (security role) | Can create roles in DEV only |
| 7 | Snowflake DEV, Cortex Agent | All earlier objects present |
| 8 | Snowflake TEST/PROD (deploy role), CI | Deploy role valid; CI reachable |
| 9 | Snowflake alerts, notification integration | Test notification delivered |

Credentials come from environment variables or a secrets manager; agents never
see or log them.

### 5.4 A later stage can send work back to an earlier one

If stage 5 finds that Q07 can't be answered because the fact table's grain is
wrong, it doesn't patch around it. It files a finding against stage 4; the
orchestrator reopens stage 4 with that finding, and every stage after 4 is
re-run and re-approved (their earlier approvals are invalidated, because their
inputs changed). Every loop is recorded in the reports, so you can see why a
stage ran twice.

### 5.5 One shared run context

All stages share one run: a `run_id`, one git branch, one config (your eight
inputs), one cost ledger (credits and tokens, cumulative), and one log. The
final report is the chain of stage reports plus the question tracker, which is
the full story of how the model was built.

---

## 6. What every stage report contains

One standard shape, so reports are comparable across stages and runs:

1. **Summary** — three lines: what was built, whether checks passed, what
   decision is needed.
2. **What was built** — files changed (with links), Snowflake objects created.
3. **Evidence** — the numbers: row counts, reconciliations, test results,
   timings, cost (credits and LLM tokens) for this stage.
4. **Checks** — each automatic check, pass/fail, with the query or command
   that produced it.
5. **Catalog problems checked** — the problem IDs this stage is responsible
   for, and the result for each.
6. **Risks and open questions** — anything the agent is unsure of. Unsure is
   reported, never guessed.
7. **Preflight** — which systems it connected to, as which role, and the check result.
8. **Question tracker** — the table from 5.2, updated for this stage.
9. **Handoff** — what's passed to the next stage, and anything sent back to an earlier one.
10. **Decision requested** — approve / request changes / stop.

Reports are written two ways from one structured object: Markdown for people
(`runs/<run>/NN_<stage>.md`, committed on the run's branch) and JSON for
machines (later also a row in a Snowflake `OPS.STAGE_REPORTS` table and a
Streamlit page for approvals). The structured object is a Pydantic model,
matching the repo's existing contracts:

```python
class Check(BaseModel):
    name: str
    passed: bool
    evidence: str          # the query/command and its result

class StageReport(BaseModel):
    run_id: str
    stage: int
    summary: str
    files_changed: list[str]
    objects_created: list[str]
    metrics: dict[str, float]
    checks: list[Check]
    catalog_results: dict[str, str]   # problem id -> "checked: ok" / "issue: ..."
    risks: list[str]
    preflight: list[Check]
    question_status: dict[str, str]   # Q-id -> status after this stage
    handoff: Handoff
    sent_back: list[str]              # findings filed against earlier stages
    decision_requested: str
```

---

## 7. How it's put together (glue + guardrails around existing tools)

**A fixed pipeline in Python code, with an existing AI assistant doing the work
inside each stage.** The stage order never changes, so it isn't left to a
model. A plain Python stage runner (glue) runs stage 0 → 9, enforces the gates
and records approvals (guardrails); inside each stage, Claude works through the
existing tools with only the permissions that stage needs. Deploys reuse the
existing Dagster `deploy_job` and Terraform rather than new code, and the
stage checks reuse `orchestration/checks.py`, dbt tests and `sql/08_validation`.

| Piece | Choice | Why |
|---|---|---|
| Orchestrator | Plain Python state machine | Deterministic order and gates; easy to test; no model cost for routing |
| Stage agents | Anthropic Python SDK, Tool Runner (`client.beta.messages.tool_runner`) | Our own tools (Snowflake, dbt, git, files) on our own machine; per-turn hooks give us approval prompts, logging and error handling |
| Model | `claude-opus-5-5` for every stage | Default for complex agentic work; cheaper models only if you choose to trade quality for cost later |
| Stage reports | Structured outputs (`client.messages.parse` with the `StageReport` model) | The report is validated against the schema, not parsed from free text |
| Tools | Read-only Snowflake SQL; write SQL only in DEV; `dbt parse/compile/test/run`; git (branch + commit, never push); file read/write inside the repo; the problem catalog | Least privilege per stage; nothing touches PROD until stage 8 approval |
| State | One git branch per run (`run/<run_id>`) + `runs/<run_id>/` folder | Every artifact and report is versioned and diffable |
| Knowledge | AGENTS.md, README, `knowledge/problem_catalog.yaml`, previous stage outputs | Same rules a human contributor follows |

Not chosen for now: an LLM orchestrator (adds cost and unpredictability to a
fixed sequence), a fleet of custom agents (the eleven roles in the problem
catalog are responsibilities, not things to build — most are already covered
by Snowflake alerts, Dagster checks, dbt tests and the Cortex Agent), Claude
Managed Agents (an option later for unattended scheduled work), and the Claude
Agent SDK (a general coding agent; we want narrow, stage-specific tools).

---

## 8. How we'll know the agents work

This repo is the answer key. It was built by hand for exactly this domain, and
in reviewing it we found four real bugs. So the first evaluation is:

1. Give the agents only the stage-0 inputs for the Alpaca domain.
2. Compare what they build with this repo, stage by stage: same grain, keys,
   metrics, governance behaviour.
3. Check they **avoid the four bugs found by hand**: dbt building into
   `GOLD_GOLD`, a run order that references tables before they exist, the row
   access policy lost on every dbt rebuild, and the session-timezone comparison
   that turned a 15-minute delay into hours.
4. Score each stage report: are the numbers real (reproducible by re-running
   the stated query), and did it flag what it didn't know?

A second, different domain later proves the agents generalise rather than
memorise this repo.

---

## 9. What already exists to build on

| Need | Already in the repo |
|---|---|
| Sample sources for offline runs | `streaming/generate_sample_*.py`, `streaming/data/sample_*.csv` |
| Contract style | `streaming/schemas.py`, `agent/schemas.py` |
| Reference outputs per stage | `sql/`, `dbt/`, `semantic_layer/` |
| Validation twins | `sql/08_validation/validation_queries.sql` |
| Checklist per stage | `knowledge/problem_catalog.yaml` |
| Rules for contributors | `AGENTS.md` |
| Replay / fault injection base | `streaming/replay_sample_data.py` |

Missing: the orchestrator, handoff and report models, preflight checks, stage
agents, tools, report renderer, a live Snowflake account, pytest + CI.

---

## 10. Build plan

**Phase 1 — offline, no accounts needed**
- Orchestrator, `StageReport` and `Handoff` models, question tracker, preflight
  framework, send-back handling, report renderer, approval prompt.
- Stage 0 (intake) and stage 1 (profiling on the sample CSVs).
- Stage 4 design half (proposes the star schema from the profile; compared with
  `dbt/models/`).
- Stage 1 connects to the live Alpaca REST API if a key is set, otherwise to the
  sample files — the preflight records which.
- Result: a real, connected run — stage 0 hands to 1, 1 hands to 4's design —
  producing reports 00, 01 and a stage-4 design report with the question
  tracker filled in up to that point.

**Phase 2 — Snowflake trial account (DEV only)**
- Stages 2, 3, 4 (build), 5, 6, 7 against DEV, with real row counts in reports.

**Phase 3 — release and operations**
- Stage 8 against TEST/PROD with approval; stage 9 hands off to the existing monitoring (Snowflake alerts, Dagster checks, runbook).

---

## 11. Decisions needed from you

1. **Business questions.** Use the four verified queries already in the
   semantic model as the start, or will you write a fuller list (recommended:
   10–30)?
2. **Approval style.** Approve every stage yourself in the terminal (simplest),
   or through a Streamlit page?
3. **Where agents write.** Agents commit to a run branch and never push (my
   recommendation), or open a pull request per stage?
4. **Model and budget.** `claude-opus-5-5` for every stage, with a per-run
   token budget you set — or do you want a cheaper model on some stages?
5. **Anthropic API access.** Phase 1 needs an Anthropic API key or an
   `ant auth login` profile on this laptop.
