# On-call runbook

One entry per alert in `sql/11_monitoring/alerts.sql` and per check in
`orchestration/checks.py`. Each entry: what it means, what to look at first,
how to fix it, and the related problems in `knowledge/problem_catalog.yaml`.

Status: written against code that hasn't run on a live account yet. Expect to
correct these steps after the first real incidents.

## Severities and routing

| Severity | Meaning | Response |
|---|---|---|
| SEV-1 | Data exposed that shouldn't be, or live data stopped during market hours | Page on-call now; fix or pause the agent within 30 minutes |
| SEV-2 | Degraded: stale for analysts, a task failing, reconciliation off | Same business day |
| SEV-3 | Warning only (freshness outside market hours, cost trend) | Next working day |

Alerts are emailed through `MARKET_AGENT_EMAIL_INT`. For a team, point the
notification integration at a webhook (Slack, PagerDuty) instead of email.

**Pausing the agent** (the safe default for any SEV-1 involving governance):
`REVOKE USAGE ON AGENT MARKET_AGENT.AGENTS.MARKET_DATA_AGENT FROM ROLE ANALYST_AGENT;`
Re-grant once fixed.

---

## silver-ingestion-stalled
**SEV-1.** `SILVER.BARS` has no bar newer than 5 minutes while the market is open.

Look, in order (the first broken link is the cause):
1. Is the market actually open? Holidays aren't modelled yet (catalog A2).
2. Producer: is `streaming/alpaca_stream_producer.py` running and logging messages? (A1 silent stall)
3. Kafka: consumer-group lag on `market-bars` growing? Connector tasks `RUNNING`? (B1, B5)
4. Snowflake: rows arriving in `BRONZE.RAW_BARS`? `SELECT MAX(_loaded_at) FROM MARKET_AGENT.BRONZE.RAW_BARS;` (C1)
5. Task: `SELECT * FROM TABLE(MARKET_AGENT.INFORMATION_SCHEMA.TASK_HISTORY(TASK_NAME => 'MERGE_BARS_TASK')) ORDER BY scheduled_time DESC LIMIT 10;` Suspended? (D2) Stream stale? `SHOW STREAMS IN SCHEMA MARKET_AGENT.BRONZE;` check `stale` (D1)

Fix: restart the failed component. After recovery, run the Dagster `backfill_job`
for the gap window so the batch path fills what the stream missed (A3, J7).

## delay-policy-detached
**SEV-1.** A Gold fact table has no `DELAYED_DATA_POLICY`; non-entitled roles,
including the agent, can see real-time prices.

1. Pause the agent (above).
2. Confirm: the `POLICY_REFERENCES` query at the end of `sql/08_validation`.
3. Cause is almost always a dbt rebuild without the post-hook: check the fact
   model's `config(post_hook=...)` in `dbt/models/marts/fct_*.sql` wasn't removed,
   and that `TRANSFORMER` still has `APPLY` on the policy.
4. Fix: re-run the Dagster `gold_refresh_job` (the post-hook re-attaches the
   policy) or attach by hand with `ALTER TABLE ... ADD ROW ACCESS POLICY ...`.
5. Re-run the policy check, then re-grant the agent.

Related: E4, G1, K8.

## pipeline-task-failed
**SEV-2.** A Bronze → Silver or news task errored in the last 15 minutes.

1. `SELECT name, error_code, error_message, scheduled_time FROM TABLE(MARKET_AGENT.INFORMATION_SCHEMA.TASK_HISTORY(ERROR_ONLY => TRUE)) ORDER BY scheduled_time DESC LIMIT 20;`
2. Duplicate keys in the MERGE source → D3/P12; the `QUALIFY` dedupe should prevent it.
3. Warehouse suspended or out of credits → check resource monitors.
4. Fix the cause, then `ALTER TASK ... RESUME;` if it auto-suspended.

## gold-stale-for-analysts
**SEV-2.** Visible `FCT_BARS` data is older than 30 minutes during market hours
(budget: 15-minute delay policy + 5-minute Gold refresh + margin).

1. Is Silver fresh? If not, it's `silver-ingestion-stalled`.
2. Did the Dagster `gold_refresh_market_hours` schedule run, and did `dbt build` pass?
   A failing dbt test stops the refresh on purpose.
3. Fix the failing test or model, then run `gold_refresh_job`.

## Dagster checks
| Check | Severity | First step |
|---|---|---|
| `fct_*_policy_attached` | ERROR (blocks deploy) | Same as delay-policy-detached |
| `fct_bars_fresh` | WARN | Same as gold-stale-for-analysts |
| `bronze_to_silver_bars_reconciled` | WARN | Compare the missing count with DLQ volume and task errors (C1, O2) |
| `silver_tasks_healthy` | ERROR | Same as pipeline-task-failed |
