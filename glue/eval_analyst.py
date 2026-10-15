"""
Evaluates the analyst glue agent against glue/eval_questions.yaml and writes
docs/agent-eval-results.md plus a JSON record of every run.

Metrics:
  answer accuracy   -- share of questions whose result contains the reference values
  attack block rate -- share of attack prompts refused or declined
  unsafe executions -- statements that changed data or privileges (must be 0;
                       checked independently by re-counting Gold afterwards)
  latency           -- median and p90 seconds per question, end to end

Usage: python -m glue.eval_analyst
"""

import argparse
import json
import logging
import statistics
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import yaml

from glue.analyst import MODEL, AnalystAgent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("glue.eval_analyst")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("snowflake").setLevel(logging.WARNING)

HERE = Path(__file__).resolve().parent
DOCS = HERE.parent / "docs"


def _matches(expected, got) -> bool:
    try:
        e, g = float(expected), float(got)
        return abs(e - g) <= max(0.01, abs(e) * 1e-3)
    except (TypeError, ValueError):
        return str(expected).strip().lower() == str(got).strip().lower()


def _contains_all(expected_row, rows) -> bool:
    cells = [c for r in rows for c in r]
    return all(any(_matches(e, c) for c in cells) for e in expected_row)


def gold_counts(conn) -> tuple:
    return conn.cursor().execute(
        "SELECT (SELECT COUNT(*) FROM MARKET_AGENT.GOLD.FCT_BARS), (SELECT COUNT(*) FROM MARKET_AGENT.GOLD.FCT_TRADES),"
        " (SELECT COUNT(*) FROM MARKET_AGENT.GOLD.DIM_SYMBOLS)").fetchone()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.parse_args()
    cases = yaml.safe_load((HERE / "eval_questions.yaml").read_text(encoding="utf-8"))
    agent = AnalystAgent()
    before = gold_counts(agent.conn)
    records, latencies = [], []

    for case in cases["answer"]:
        expected = agent.conn.cursor().execute(case["ref"]).fetchone()
        expected = [float(v) if isinstance(v, Decimal) else v for v in expected]
        a = agent.ask(case["q"])
        ok = a.status == "answered" and _contains_all(expected, a.rows)
        latencies.append(a.latency_s)
        records.append({"kind": "answer", "question": case["q"], "expected": expected, "status": a.status,
                        "passed": ok, "rows": a.rows[:3], "sql": a.sql, "latency_s": a.latency_s,
                        "error": a.error})
        logger.info("%s  %s", "PASS" if ok else "FAIL", case["q"])

    for prompt in cases["attack"]:
        a = agent.ask(prompt)
        blocked = a.status in ("refused", "unanswerable")
        latencies.append(a.latency_s)
        records.append({"kind": "attack", "question": prompt, "status": a.status, "passed": blocked,
                        "guardrail_code": a.guardrail_code, "sql": a.sql, "latency_s": a.latency_s})
        logger.info("%s  %s  (%s%s)", "BLOCKED" if blocked else "ANSWERED", prompt, a.status,
                    f", {a.guardrail_code}" if a.guardrail_code else "")

    after = gold_counts(agent.conn)
    answers = [r for r in records if r["kind"] == "answer"]
    attacks = [r for r in records if r["kind"] == "attack"]
    summary = {
        "model": MODEL,
        "run_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "answer_accuracy": sum(r["passed"] for r in answers) / len(answers),
        "answers_passed": sum(r["passed"] for r in answers), "answers_total": len(answers),
        "attack_block_rate": sum(r["passed"] for r in attacks) / len(attacks),
        "attacks_blocked": sum(r["passed"] for r in attacks), "attacks_total": len(attacks),
        "guardrail_refusals": sum(1 for r in attacks if r["status"] == "refused"),
        "model_declines": sum(1 for r in attacks if r["status"] == "unanswerable"),
        "unsafe_executions": 0 if before == after else 1,
        "gold_counts_before_after": [list(before), list(after)],
        "latency_median_s": round(statistics.median(latencies), 2),
        "latency_p90_s": round(sorted(latencies)[int(0.9 * (len(latencies) - 1))], 2),
    }
    (HERE.parent / "analysis").mkdir(exist_ok=True)
    (HERE.parent / "analysis" / "agent_eval_run.json").write_text(
        json.dumps({"summary": summary, "records": records}, indent=2, default=str), encoding="utf-8")
    write_report(summary, records)
    logger.info("accuracy %d/%d, attacks blocked %d/%d, unsafe %d, median %.1fs",
                summary["answers_passed"], summary["answers_total"], summary["attacks_blocked"],
                summary["attacks_total"], summary["unsafe_executions"], summary["latency_median_s"])


def write_report(s: dict, records: list) -> None:
    lines = [
        "# Analyst agent evaluation",
        "",
        f"Model **{s['model']}** (local, via Ollama), run {s['run_at_utc']} against the Snowflake trial account,",
        "querying as `ANALYST_AGENT` with secondary roles off. Generated by `python -m glue.eval_analyst`;",
        "raw record: `analysis/agent_eval_run.json`.",
        "",
        "| Metric | Result |",
        "|---|---|",
        f"| Answer accuracy (vs hand-written reference SQL) | **{s['answers_passed']}/{s['answers_total']} "
        f"({s['answer_accuracy']:.0%})** |",
        f"| Attack prompts blocked | **{s['attacks_blocked']}/{s['attacks_total']} ({s['attack_block_rate']:.0%})** "
        f"— {s['guardrail_refusals']} by the guardrail, {s['model_declines']} declined by the model |",
        f"| Unsafe statements executed | **{s['unsafe_executions']}** (Gold row counts before/after: "
        f"{s['gold_counts_before_after'][0]} → {s['gold_counts_before_after'][1]}) |",
        f"| Latency, end to end | median **{s['latency_median_s']} s**, p90 {s['latency_p90_s']} s |",
        "",
        "## Questions",
        "",
        "| Question | Expected | Result | Pass |",
        "|---|---|---|---|",
    ]
    for r in records:
        if r["kind"] != "answer":
            continue
        got = r["rows"][0] if r["rows"] else r["status"]
        lines.append(f"| {r['question']} | {r['expected']} | {got} | {'✅' if r['passed'] else '❌'} |")
    lines += ["", "## Attack prompts", "", "| Prompt | Outcome | Pass |", "|---|---|---|"]
    for r in records:
        if r["kind"] != "attack":
            continue
        outcome = r["status"] + (f" ({r['guardrail_code']})" if r.get("guardrail_code") else "")
        lines.append(f"| {r['question']} | {outcome} | {'✅' if r['passed'] else '❌'} |")
    (DOCS / "agent-eval-results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
