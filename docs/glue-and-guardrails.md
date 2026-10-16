# Glue agents and guardrails

**Principle.** The stack already exists: Snowflake (Streams, Tasks, row access
policies, resource monitors), dbt, Dagster, Terraform, GitHub Actions, Kafka,
OpenTelemetry. None of it is rebuilt here. What this repo adds is what
companies add around such a stack:

1. **Glue agents** that do the repetitive human part of the work (gathering
   context across systems, diagnosing, drafting the fix) by calling the
   existing tools.
2. **Guardrails** that decide what an agent may do on its own, what needs a
   human, and that record everything.

The goal is to remove repetitive human work, not human judgement: an agent
never changes production, access or money without a person approving it.

**Why a local model.** Both agents run on qwen3:14b (and nomic-embed-text for
search) served by Ollama on the laptop's GPU (RTX 5070 Ti, 12 GB). Questions,
table data, schemas and error messages never go to a model vendor, which is
the main reason companies hold back from letting AI near their data. It also
costs nothing per call.

---

## 1. The two agents

| Agent | Triggered by | Uses these existing tools | Produces | Results |
|---|---|---|---|---|
| **Analyst** (`glue/analyst.py`) | A plain-English question | Snowflake as `ANALYST_AGENT` on `ANALYST_WH` | The answer, straight from executed SQL, with the SQL and an as-of time | 13/15 reference questions, 8/8 attacks blocked, 0 unsafe executions ([agent-eval-results.md](agent-eval-results.md)) |
| **Pipeline doctor** (`glue/doctor.py`) | A failed check (`cicd/snowflake_ci.py`) | Snowflake (read-only SQL on a clone), dbt, the problem catalog | A diagnosis with evidence, a fix applied and verified in the clone, and the production fix for approval, or an escalation | 5/5 injected faults diagnosed correctly: 4 fixed and verified in a clone, 1 escalated to a human, no false alarm, 0 production writes ([doctor-eval-results.md](doctor-eval-results.md)) |

The analyst answers questions; the doctor acts. Given a failed check, the
doctor works in a loop with no one prompting it:

1. **Investigate:** writes its own read-only SQL against the throwaway clone
   to see the rows behind each failing check.
2. **Research:** searches the 158-problem catalog (`knowledge/problem_catalog.yaml`)
   with hybrid search: local embeddings plus IDF-weighted keywords.
3. **Decide:** submits a diagnosis that cites a catalog problem, with evidence,
   and picks one runbook action.
4. **Act:** the code (not the model) runs that action's SQL in the clone and
   re-runs dbt.
5. **Verify:** re-runs all eight checks. A fix that doesn't hold is escalated.
6. **Hand off:** writes a report with the exact production SQL, which runs
   only through the approval-gated deploy.

---

## 2. Guardrails, layer by layer

Every rule below is enforced in code or by Snowflake, not by the prompt.

| Layer | Analyst | Pipeline doctor |
|---|---|---|
| What the model can read | One read-only SELECT on the four Gold tables, row cap 1,000 (`glue/guardrails.py`, sqlglot AST) | One read-only SELECT on the clone's Silver and Gold tables, row cap 20 (same guardrail, its own allowlist) |
| What the model can change | Nothing | Nothing directly: it can only name one of four human-written runbook actions (`dedupe_silver_bars`, `quarantine_bad_bars`, `rebuild_gold`, `escalate`) |
| Where changes can happen | — | Only in a database named `MARKET_AGENT_CI_*`; runbook SQL that mentions `MARKET_AGENT.` is refused |
| Database-side limits | `ANALYST_AGENT` role, secondary roles off, 15-minute delay policy, 30 s statement timeout, credit monitor | Runs as `CI_RUNNER` in CI, which owns only the clone |
| Grounding | Data facts in the prompt (dates, symbols); numbers come only from executed SQL | A diagnosis must cite a catalog ID that a search actually returned, or it is sent back |
| Budgets | 3 attempts per question | 8 model steps; running out ends in `escalate` |
| Unknown or failed actions | Refused, never retried for policy violations | Unknown action or unverified fix → `escalate` |
| Audit | One row per question in `GOVERNANCE.AGENT_QUERY_AUDIT_LOG` (append-only) | Full transcript of every model turn and tool call in the report |

Unit tests for these rules: `tests/test_guardrails.py` (23) and
`tests/test_doctor.py` (13).

---

## 3. CI/CD: where a human still decides

| Step | Who | Tool |
|---|---|---|
| Pull request: build and test on a zero-copy clone of Silver, then drop it | Automatic | `.github/workflows/snowflake-ci.yml`, `cicd/snowflake_ci.py` |
| Failed check: diagnose, fix in the clone, verify | Pipeline doctor | `glue/doctor.py` |
| Merge to master | Human review | GitHub |
| Deploy to `MARKET_AGENT` | **Human approval** (GitHub `production` environment) | `.github/workflows/snowflake-cd.yml` |
| Post-deploy checks on production | Automatic | `cicd/snowflake_ci.py verify` |
| Anything the doctor escalates | Human, starting from its diagnosis | — |

CI and CD connect as a dedicated key-pair service user, `CI_DEPLOY`
(`sql/12_cicd/ci_deploy_user.sql`): `CI_RUNNER` for pull requests, which can
only read Silver and create the throwaway database, and `TRANSFORMER` for the
approved deploy.

---

## 4. How human work drops

| Before | Now |
|---|---|
| A check fails; an engineer reads logs, queries tables, works out the cause, writes and tests a fix | The doctor delivers a diagnosis with evidence and a fix already verified in a clone; the engineer approves or takes over |
| Changes are tested by running SQL by hand against the real database | Each pull request is built and tested on a clone of real data automatically |
| Production deploys are SQL run by hand | One approval click; the deploy and its checks run themselves |
| Analysts wait for an engineer to write a query | The analyst agent answers from governed data, within the delay policy |
