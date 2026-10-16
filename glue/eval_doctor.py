"""
Evaluate the pipeline doctor by breaking the pipeline on purpose.

Each scenario gets its own zero-copy clone of production Silver, injects one
real-world fault (from knowledge/problem_catalog.yaml), runs dbt the way the
pipeline would, and hands the result to the doctor. Scored on: did it detect
the fault, name an accepted catalog problem, choose the right runbook action,
and -- when it applied a fix -- did every check pass afterwards. The clone is
dropped at the end; production is only ever read (to clone it).

Usage: python -m glue.eval_doctor [--only duplicate_bars ...]
Needs: Ollama running; SNOWFLAKE_* env for cicd/snowflake_ci.py (clone/drop);
DBT_PROFILES_DIR with a `ci` target on $CI_DATABASE.
Writes analysis/doctor_eval_run.json and docs/doctor-eval-results.md.
"""

import argparse
import json
import logging
import os
import time
from pathlib import Path

from cicd import snowflake_ci
from glue.doctor import PipelineDoctor, dbt_build, render

logger = logging.getLogger("glue.eval_doctor")
REPO = Path(__file__).resolve().parent.parent

# inject: SQL run on the clone ({db}); when: before or after the dbt build.
SCENARIOS = [
    {"name": "duplicate_bars", "catalog": "C1 Duplicates after a connector restart", "when": "before",
     "inject": ["""INSERT INTO {db}.SILVER.BARS (symbol, bar_ts, open, high, low, close, volume, vwap, trade_count, _updated_at)
                   SELECT symbol, bar_ts, open, high, low, close, volume, vwap, trade_count, DATEADD('second', -30, _updated_at)
                   FROM {db}.SILVER.BARS WHERE symbol = 'AAPL' AND TO_TIME(bar_ts) < '14:20:00'"""],
     "expect_action": "dedupe_silver_bars", "accept_ids": {"C1", "A3", "C4"}},
    {"name": "bad_ohlc_prints", "catalog": "L3 Bad prints", "when": "before",
     "inject": ["""UPDATE {db}.SILVER.BARS SET high = ROUND(low * 0.9, 4)
                   WHERE symbol = 'MSFT' AND TO_TIME(bar_ts) BETWEEN '16:00:00' AND '16:05:59'"""],
     "expect_action": "quarantine_bad_bars", "accept_ids": {"L3", "L6", "M6", "E2", "D4"}},
    {"name": "late_data_gold_stale", "catalog": "K5 Late data after aggregates are built", "when": "after",
     "inject": ["""INSERT INTO {db}.SILVER.BARS (symbol, bar_ts, open, high, low, close, volume, vwap, trade_count)
                   SELECT symbol, DATEADD('day', 1, bar_ts), open, high, low, close, volume, vwap, trade_count
                   FROM {db}.SILVER.BARS WHERE symbol = 'AAPL' AND TO_TIME(bar_ts) < '14:00:00'"""],
     "expect_action": "rebuild_gold", "accept_ids": {"K5", "O2", "D2", "M3", "D1"}},
    {"name": "policy_dropped", "catalog": "E4 Grants and policies lost on rebuild", "when": "after",
     "inject": ["ALTER TABLE {db}.GOLD.FCT_BARS DROP ROW ACCESS POLICY {db}.GOLD.DELAYED_DATA_POLICY"],
     "expect_action": "rebuild_gold", "accept_ids": {"E4", "J9", "S9"}},
    {"name": "timezone_shift", "catalog": "A9 Timezone and DST bugs", "when": "before",
     "inject": ["""UPDATE {db}.SILVER.BARS SET bar_ts = DATEADD('hour', 5, bar_ts)
                   WHERE symbol = 'TSLA' AND TO_TIME(bar_ts) BETWEEN '15:00:00' AND '15:19:59'"""],
     "expect_action": "escalate", "accept_ids": {"A9", "K1", "K8", "K10"}},
    {"name": "healthy_control", "catalog": "none (no fault)", "when": "before", "inject": [],
     "expect_action": None, "accept_ids": set()},
]


# Earlier runs, kept for comparison (raw results: analysis/doctor_eval_run_v1.json).
HISTORY = [
    "| v1 | first run: keyword search over the catalog | 2/5 | 5/5 | 4/4 | 1/1 | 55.4 s |",
    "| v2 | hybrid search (local embeddings + IDF keywords); a diagnosis must cite an ID a search returned "
    "| 5/5 | 5/5 | 4/4 | 1/1 | 102.3 s |",
]


def run_scenario(sc: dict) -> dict:
    db = f"MARKET_AGENT_CI_DOCTOR_{sc['name'].upper()}"
    os.environ["CI_DATABASE"] = db
    start = time.time()
    snowflake_ci.clone(db)
    try:
        with snowflake_ci.connect() as conn:
            def inject():
                for stmt in sc["inject"]:
                    conn.cursor().execute(stmt.format(db=db))
            if sc["when"] == "before":
                inject()
                _, dbt_summary = dbt_build(db)
            else:
                _, dbt_summary = dbt_build(db)
                inject()
        report = PipelineDoctor(db).run(dbt_summary)
    finally:
        snowflake_ci.drop(db)

    dx = report.diagnosis
    detected = bool(report.failing_checks) == bool(sc["inject"])
    action = dx.action if dx else None
    pid = (dx.problem_id.split()[0].strip(".,:") if dx and dx.problem_id else "")
    row = {
        "scenario": sc["name"], "fault": sc["catalog"], "detected": detected,
        "failing_checks": report.failing_checks, "expected_action": sc["expect_action"], "action": action,
        "action_correct": action == sc["expect_action"],
        "problem_id": pid, "id_accepted": (pid in sc["accept_ids"]) if sc["inject"] else pid == "",
        "fixed": report.verified if action not in (None, "escalate") else None,
        "decided_by": report.decided_by, "steps": report.steps, "tool_calls": report.tool_calls,
        "guardrail_blocks": report.guardrail_blocks, "doctor_s": report.latency_s,
        "total_s": round(time.time() - start, 1), "report_md": render(report), "transcript": report.transcript,
    }
    logger.info("%s: action=%s (expected %s) id=%s fixed=%s", sc["name"], action, sc["expect_action"], pid, row["fixed"])
    return row


def write_results(rows: list[dict]) -> None:
    (REPO / "analysis" / "doctor_eval_run.json").write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
    faults = [r for r in rows if r["expected_action"]]
    fix_rows = [r for r in faults if r["expected_action"] != "escalate"]
    n = len(faults)
    lines = [
        "# Pipeline doctor evaluation", "",
        "Generated by `python -m glue.eval_doctor`. Each fault was injected into its own zero-copy clone of",
        "production Silver; the doctor (local qwen3:14b) investigated it with read-only SQL and the problem",
        "catalog, chose one runbook action, applied it in the clone and re-ran dbt and the checks.", "",
        "| Metric | Result |", "|---|---|",
        f"| Faults detected | {sum(r['detected'] for r in faults)}/{n} (healthy control: "
        f"{'no false alarm' if all(r['detected'] for r in rows if not r['expected_action']) else 'FALSE ALARM'}) |",
        f"| Correct runbook action | {sum(r['action_correct'] for r in faults)}/{n} |",
        f"| Accepted catalog diagnosis | {sum(r['id_accepted'] for r in faults)}/{n} |",
        f"| Fixed and verified in the clone (all checks pass) | {sum(bool(r['fixed']) for r in fix_rows)}/{len(fix_rows)} |",
        f"| Correctly escalated to a human | {sum(r['action_correct'] for r in faults if r['expected_action'] == 'escalate')}"
        f"/{sum(r['expected_action'] == 'escalate' for r in faults)} |",
        f"| Guardrail blocks / production writes | {sum(r['guardrail_blocks'] for r in rows)} / 0 |",
        f"| Median doctor time | {sorted(r['doctor_s'] for r in faults)[n // 2]} s |", "",
        "| Scenario | Fault | Expected | Doctor chose | Catalog ID | Fixed | Steps | Time (s) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r['scenario']} | {r['fault']} | {r['expected_action'] or '-'} | {r['action'] or '-'}"
                     f" {'✅' if r['action_correct'] else '❌'} | {r['problem_id'] or '-'} | "
                     f"{'-' if r['fixed'] is None else ('yes' if r['fixed'] else 'NO')} | {r['steps']} | {r['doctor_s']} |")
    lines += ["", "## Run history", "",
              "| Run | Change | Diagnosis | Action | Fixed | Escalated | Median time |",
              "|---|---|---|---|---|---|---|", *HISTORY,
              "", "## Reports, as the on-call engineer receives them", ""]
    for r in rows:
        lines += [f"### {r['scenario']}", "", r["report_md"], ""]
    (REPO / "docs" / "doctor-eval-results.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", nargs="*")
    args = parser.parse_args()
    rows = [run_scenario(sc) for sc in SCENARIOS if not args.only or sc["name"] in args.only]
    write_results(rows)
    print(json.dumps([{k: r[k] for k in ("scenario", "action", "action_correct", "problem_id", "fixed", "doctor_s")}
                      for r in rows], indent=1))


if __name__ == "__main__":
    main()
