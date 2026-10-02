# Production readiness: existing tools, glue and guardrails

The approach companies actually take: **don't rebuild what a mature tool already
does.** Use existing tools for the heavy lifting, and write only two things
ourselves:

- **Glue** — the code and config that connects the tools so they work as one
  pipeline (deploy order, handoffs, credentials wiring, schedules).
- **Guardrails** — the checks, policies, limits and approvals that keep the
  tools (and the AI agent) from doing damage.

Status: everything below is written; Terraform and the Dagster graph are
validated locally; none of it has run against live Snowflake, GCP or Kafka yet.

---

## 0. The goal: remove human work, keep human judgement

What companies want from this kind of platform is not "no humans" — it's
**no humans doing repetitive operational work**. People should decide, approve
and handle real exceptions; machines should do everything that's the same
every time. Every piece below exists to move a task from the left column to
the right.

| Task | Before (manual) | Now | Human role now |
|---|---|---|---|
| Create bucket, Pub/Sub, IAM grants, integrations | Console clicks + copying service-account names between clouds | Terraform | Approve the plan |
| Run ~10 SQL files in the right order | By hand, from a README that had the order wrong | Dagster `deploy_job` derives the order | None |
| Rebuild Gold | Someone runs `dbt run` | Every 5 minutes in market hours | None |
| Keep the licensing policy attached | Remember after every rebuild | dbt post-hook + blocking check | Only if it pages |
| Notice stalls, failures, stale data | Someone looks at dashboards | Snowflake alerts + Dagster checks | Respond to a page, using the runbook |
| Fill gaps the live stream missed | Manual backfill script | Nightly backfill schedule | None |
| Check a change is safe | Read the code and hope | CI on every push | Code review |
| Deploy to production | Run things by hand | Approval-gated deploy workflow | One approval |
| Answer analysts' data questions | An engineer writes SQL | Cortex Agent over the governed semantic layer | Review answers flagged as unverified |
| Cap spend | Watch the bill | Resource monitor, statement timeouts | Set the budget |

**Human decisions that deliberately stay human** — high-impact or hard to undo:
approving infrastructure and production changes; reviewing code; granting
real-time entitlements (`REALTIME_DESK`); approving new metric definitions;
responding to SEV-1 pages (with "pause the agent" as the safe default).

Rule for anything new: if a task is the same every time, automate it; if it
changes money, access or production, gate it behind one human approval; if it
can't be undone, it needs both.

---

## 1. What each tool does, and what we write around it

| Job | Existing tool (adopt, don't build) | Glue we write | Guardrails we write |
|---|---|---|---|
| Market data | Alpaca API | `streaming/` producers and backfills | Pydantic contracts + DLQ for malformed messages |
| Streaming transport | Kafka + Kafka Connect | Connector config | DLQ topic; lag watched by on-call (runbook) |
| Loading | Snowpipe Streaming, Snowpipe | `sql/01_ingest`, `infra/terraform` (bucket, Pub/Sub, IAM) | Permissive Bronze types so loads never silently drop rows |
| Bronze → Silver | Snowflake Streams + Tasks | `sql/03_silver` | Dedupe on keys (`QUALIFY`); reconciliation check |
| Silver → Gold | dbt | `dbt/` models | dbt tests; schema macro; policy post-hook |
| Orchestration | **Dagster** | `orchestration/` asset graph and schedules | Blocking checks stop deploys on bad or ungoverned data |
| Infrastructure | **Terraform** | `infra/terraform/` | Least-privilege roles; key-pair auth; credit monitor |
| CI/CD | **GitHub Actions** | `.github/workflows/` | Every PR validated; production deploy needs approval |
| Semantic layer | Snowflake Semantic Views, Cortex Analyst | `semantic_layer/` | Verified queries + hand-written SQL twins |
| Document search | Cortex Search | `sql/04_documents` | Agent cites sources or makes no news claim |
| AI agent | **Snowflake Cortex Agent** (not a custom agent) | `sql/10_agent`, MCP server, Streamlit, FastAPI | Row access policy, read-only agent role, audit log, statement timeout |
| Monitoring | Snowflake ALERTs + Dagster asset checks | `sql/11_monitoring`, `orchestration/checks.py` | Paging on stalls, policy loss, task failures, staleness |
| On-call | Email / webhook (PagerDuty, Slack) | Notification integration | `docs/runbook.md` |
| Data observability | Built in for now (see §6) | — | dbt tests, reconciliation, freshness |
| Data catalog | dbt docs + Dagster lineage for now (see §6) | — | Column descriptions in `schema.yml` |

The problem catalog (`knowledge/problem_catalog.yaml`) is the specification for
the guardrails: each check, alert and policy here points at the problem it
prevents.

---

## 2. Orchestrator: Dagster, alongside Snowflake Tasks

**Split of responsibilities**

| Runs in Snowflake Tasks | Runs in Dagster |
|---|---|
| Bronze → Silver MERGEs every minute (trades, bars) and every 15 minutes (symbols, news) | Deploying every SQL file in dependency order |
| | dbt build (Gold) every 5 minutes in market hours |
| | Semantic view, Cortex Agent, monitoring deploys |
| | Nightly Alpaca → GCS backfill |
| | Guardrail checks every 15 minutes |

Why keep Tasks: minute-level merges belong next to the data; running them from
an external scheduler would add latency, cost and a failure point for no gain.
Dagster handles what crosses systems or needs ordering, lineage and checks.

Why Dagster over Airflow: Airflow is the most widely deployed, but it doesn't
run natively on Windows (this project's dev machine), and Dagster's
asset-based model fits this project directly — the deploy order is derived from
declared dependencies, so it can't drift the way the README's run order did
(see §7). dbt models appear as assets automatically (`dagster-dbt`).

Run it: `dagster dev -m orchestration.definitions` (UI at localhost:3000).

---

## 3. Infrastructure as code: Terraform

`infra/terraform/` owns account-level objects; `sql/` and `dbt/` own data
objects.

| Terraform | sql/ and dbt/ |
|---|---|
| GCS bucket (lifecycle, no public access), Pub/Sub topic, subscription, bucket notification | Schemas, tables, streams, tasks, pipes |
| GCP IAM for Snowflake's service accounts (replaces manual console steps) | Row access policy, grants on data objects |
| Snowflake database, `ANALYST_WH`, credit monitor, functional roles + SYSADMIN hierarchy | Semantic view, search service, agent, alerts |
| Storage and notification integrations | dbt models and tests |

Known overlap: `sql/` still has `CREATE ... IF NOT EXISTS` for the database,
`ANALYST_WH`, the monitor, roles and integrations, so the SQL runs on an
account without Terraform. After `terraform apply` those statements are no-ops.
The two definitions must stay identical; once the Terraform path is verified
live, remove the SQL copies.

Validated with `terraform validate` against the real providers (Snowflake 2.21,
Google 7.x). Not yet applied.

---

## 4. CI/CD

**CI** (`.github/workflows/ci.yml`, every push and pull request):
compile all Python; run the sample-data generators; validate the problem
catalog and build the playbook; `dbt parse`; load and validate the Dagster
graph; `terraform fmt -check` and `terraform validate`.

**CD** (`.github/workflows/deploy.yml`, manual trigger only): runs in a GitHub
`production` environment, which should require a reviewer's approval. Steps:
`terraform plan` → (approval) → `terraform apply` → Dagster `deploy_job`.
Requires repository secrets (listed in the workflow). Not yet run.

Still missing: a pytest suite (README "Target"), so CI checks that things load
and parse, not yet that they behave correctly.

---

## 5. Monitoring, alerting and on-call

Two layers on purpose:

- **Snowflake ALERTs** (`sql/11_monitoring/alerts.sql`) run on Snowflake's own
  scheduler, so they fire even if Dagster is down: live ingestion stalled
  (SEV-1), delay policy detached (SEV-1), task failed (SEV-2), Gold stale for
  analysts (SEV-2).
- **Dagster checks** (`orchestration/checks.py`) run after each Gold refresh
  and every 15 minutes; the policy checks are *blocking*, so nothing deploys on
  top of ungoverned data.

On-call procedure, severities and the "pause the agent" step:
`docs/runbook.md`. Credit spend is capped by `ANALYST_AGENT_MONITOR`.

---

## 6. Observability and catalog: when to buy

For one pipeline and one team, the built-in pieces are enough: dbt tests,
reconciliation and freshness checks, Snowflake alerts, dbt docs and Dagster's
lineage graph as the catalog.

Buy a data observability tool (for example Monte Carlo) when there are many
pipelines and unknown failure modes: they learn normal volume and schema
patterns across hundreds of tables, which hand-written checks can't. Buy a
catalog (for example Atlan or Alation) when many teams need to find, trust and
request data. Both integrate with what's already here: they read Snowflake's
`ACCESS_HISTORY` and `QUERY_HISTORY`, dbt's manifest, and Dagster's metadata,
so nothing here would be thrown away.

---

## 7. Why real-time — and what deliberately isn't

Real-time is justified here because the product is prices: a stock price an
hour old is a different fact. But real-time costs more at every layer, so only
the parts that need it are real-time.

**Freshness budget (live path)**

| Hop | Target | Mechanism |
|---|---|---|
| Alpaca → Kafka | seconds | Websocket producer |
| Kafka → Bronze | seconds | Snowpipe Streaming |
| Bronze → Silver | ≤ 1 minute | Task every minute |
| Silver → Gold | ≤ 5 minutes | dbt build every 5 minutes in market hours |
| Gold → non-entitled users and the agent | +15 minutes | `DELAYED_DATA_POLICY` (licensing, intentional) |
| **Visible to the agent** | **≈ 15–21 minutes**, alert at 30 | |
| Visible to `REALTIME_DESK` | ≈ 1–6 minutes | |

**Deliberately batch**

| Data | Why batch is enough |
|---|---|
| Symbol reference data | Changes rarely; daily load |
| Historical bars | Backfill only; nightly Alpaca REST pull fills stream gaps |
| News | Search index lag of 1 hour is acceptable for "why did it move" questions |

Note: before this change, Gold was only refreshed by hand, which would have
made the "real-time" claim untrue for anyone querying through the agent. The
5-minute schedule fixes that; at larger data volumes, the fact models should
become incremental (catalog E1) or Dynamic Tables to keep the 5-minute budget
affordable.
