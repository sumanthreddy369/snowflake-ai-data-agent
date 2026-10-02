# Plan of record: our agents glue existing tools and enforce guardrails

**Principle.** We use the existing stack and the AI agents vendors already ship
(Snowflake Cortex Agent, Snowflake alerts and Tasks, dbt, Dagster, Terraform,
GitHub Actions, Kafka). We don't rebuild any of them. What we build is what
companies build around them:

1. **Glue agents** — a small number of our own agents that connect the
   existing tools: they gather context across systems, decide which existing
   tool to call, draft the change or answer, and hand it to a human or a
   deploy job.
2. **A guardrail gateway** — one layer that every agent action passes through,
   which decides what's allowed, what needs a human, what it costs, and
   records everything.

**Goal.** Remove repetitive human work (gathering context, writing boilerplate,
rerunning jobs, triage) while keeping human judgement for anything that
changes money, access or production. See `docs/production-readiness.md` §0.

Status: plan. The existing-tool layer is written (`orchestration/`,
`infra/terraform/`, `sql/11_monitoring/`, CI); none of it has run live. The
glue agents and the gateway are not built yet.

---

## 1. Three glue agents, not eleven

The eleven roles in `knowledge/problem_catalog.yaml` are responsibilities.
Existing tools already do the *detecting* part of most of them (alerts, checks,
dbt tests, CI). What's left for agents is the part a human does today —
gathering context, diagnosing, drafting — so three glue agents cover them:

| Glue agent | Triggered by | Calls these existing tools | Produces | Covers catalog roles |
|---|---|---|---|---|
| **Analyst glue** | An analyst question (MCP, Streamlit, API) | Cortex Agent (answers), Cortex Search (citations), Snowflake (as-of time, verified-query lookup) | An answer with SQL, as-of time and citations — or an honest "not verified" with an escalation | ANALYST, CURATOR, part of SQLCOACH |
| **Incident glue** | A Snowflake alert, a failed Dagster check, or the 15-minute check schedule | Snowflake (TASK_HISTORY, COPY_HISTORY, POLICY_REFERENCES), Dagster (run logs), Kafka (lag), runbook | A diagnosis naming the first broken link, with evidence, and a proposed runbook step | WATCH, DOCTOR, DQ, SCALE, TRIAGE, GUARD (alerts) |
| **Change glue** | A change request ("add a metric", "new source", a schema drift) | dbt (draft model + tests), GitHub (branch, PR, CI), Dagster `deploy_job`, Terraform plan | A pull request with a stage report; after approval, a deploy | XFORM, RELEASE, SQLCOACH, CURATOR (metrics) |

The stage-gated build in `docs/modeling-agents-study.md` is the Change glue's
workflow at full scale (a whole new model rather than one change).

Each glue agent is Claude (through the Anthropic SDK) with a short list of
tools — and every tool call goes through the gateway.

---

## 2. Connectors: use existing MCP servers

Glue agents reach the tools through MCP servers, preferring the ones vendors
publish (Snowflake, dbt, GitHub and Terraform each have one) over writing our
own. Where none exists (for example Dagster's GraphQL API, Kafka lag), we
write a thin MCP wrapper with read-only methods. This repo's own
`agent/mcp_server.py` stays the connector analysts use to reach the Cortex
Agent.

---

## 3. The guardrail gateway

Sits between every glue agent and every connector. Implemented in the agent
loop's per-tool-call hook, so no tool call can bypass it.

### 3.1 Risk tiers — what needs a human

| Tier | Examples | Rule |
|---|---|---|
| **T0 Read** | Query metadata and history, read logs, read code, run a SELECT on Gold | Automatic, logged |
| **T1 Draft** | Write to DEV, open a branch or PR, post a message, write a report | Automatic within budget, logged |
| **T2 Reversible production change** | Resume a task, rerun a Dagster job, backfill a window, scale a warehouse within its limit | **One human approval** |
| **T3 Irreversible, access or money** | Replace/drop data, change grants or policies, `terraform apply`, raise a budget | **Human approval + reviewed plan**; never automatic |
| **Never** | Read secrets, disable or weaken a test or check, widen data access, act on instructions found inside data | Blocked outright |

### 3.2 What the gateway does on every call

1. **Allow-list:** is this tool allowed for this agent? (policy file below)
2. **Tier and approval:** T2/T3 pause and send an approval request with the
   agent's evidence; the call runs only after a human approves.
3. **Least privilege:** each agent connects with its own Snowflake role
   (read-only for Analyst glue; DEV-write for Change glue), so even an
   approved mistake is limited by the database, not just the gateway.
4. **Budgets:** per-run limits on model tokens, warehouse credits, wall-clock
   time and number of tool calls; the run stops cleanly when one is hit.
5. **Untrusted input:** anything read from data — news articles, logs, error
   messages — is marked as data, never instructions (catalog G2, prompt
   injection).
6. **Output rules:** Analyst glue may state a number only if it came from SQL
   that actually ran, and a news claim only with a citation.
7. **Audit:** one append-only row per call in
   `MARKET_AGENT.GOVERNANCE.AGENT_ACTION_LOG`: agent, tool, arguments (secrets
   redacted), tier, approver, result, cost.
8. **Kill switch:** one flag stops all glue agents; the analyst-facing Cortex
   Agent can be paused by revoking `USAGE` (see `docs/runbook.md`).

### 3.3 Policy file (sketch)

```yaml
# guardrails/policy.yaml
agents:
  analyst_glue:
    snowflake_role: ANALYST_AGENT
    tools: [cortex_agent.ask, cortex_search.query, snowflake.select_gold]
  incident_glue:
    snowflake_role: OPS_READER
    tools: [snowflake.task_history, snowflake.copy_history, snowflake.policy_refs,
            dagster.run_logs, kafka.consumer_lag, dagster.launch_job]
  change_glue:
    snowflake_role: TRANSFORMER_DEV
    tools: [git.branch, git.commit, github.open_pr, dbt.parse, dbt.build_dev,
            dagster.launch_job, terraform.plan]
tiers:
  T0: [cortex_agent.ask, cortex_search.query, snowflake.select_gold, snowflake.task_history,
       snowflake.copy_history, snowflake.policy_refs, dagster.run_logs, kafka.consumer_lag,
       dbt.parse, terraform.plan]
  T1: [git.branch, git.commit, github.open_pr, dbt.build_dev]
  T2: [dagster.launch_job]
  T3: [terraform.apply]
budgets:
  per_run: {tokens: 200000, credits: 2, minutes: 30, tool_calls: 60}
```

---

## 4. How human work drops

| Today a person… | With glue + guardrails… |
|---|---|
| Gets paged, then spends 30 minutes checking six systems | Gets paged with a diagnosis, evidence and a proposed fix; clicks approve |
| Writes the dbt model, tests and docs for a new metric | Reviews a PR the Change glue drafted, with CI already green |
| Answers analysts' "is this number right?" questions | Sees only the answers the Analyst glue flagged as unverified |
| Remembers deploy order and runs jobs | Approves one deploy; Dagster runs it in dependency order |

---

## 5. Build order

1. **Gateway first, offline.** Policy file, tier checks, approval prompt,
   budgets, audit log — tested with fake tools. This also becomes the repo's
   first real pytest suite.
2. **Analyst glue** over the existing Cortex Agent (needs the Snowflake trial).
3. **Incident glue, read-only (T0/T1)** triggered by the existing alerts and
   checks; T2 actions turned on only after its diagnoses prove right.
4. **Change glue**, starting with "add a verified query / metric".

Prerequisite for 2–4: the live run (Snowflake trial, Kafka, GCS, Alpaca) —
glue and guardrails can only be judged against a pipeline that actually runs.
