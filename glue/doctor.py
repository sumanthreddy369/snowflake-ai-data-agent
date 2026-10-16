"""
Pipeline doctor: the agentic glue agent. When checks fail, it investigates,
diagnoses, fixes what is safe to fix, verifies, and hands a human only the
decision that needs one.

    failed checks -> investigate (read-only SQL, problem catalog, dbt results)
      -> diagnose (catalog problem ID + evidence) -> pick ONE runbook action
      -> apply it in the throwaway clone -> re-run dbt + checks -> report,
         with the production action waiting for human approval

It runs on a local model (Ollama, default qwen3:14b), so no data, schema or
error text is sent to an AI vendor. The model never writes changes itself:
  - its only data access is `run_sql`, checked by glue/guardrails.py (one
    read-only SELECT, only the clone's Silver and Gold tables, 20-row cap);
  - its only way to change anything is to name an action from RUNBOOK; the
    SQL for each action is written here, by people, and only ever runs in a
    database whose name starts with MARKET_AGENT_CI_;
  - it has a step budget; running out, an unknown action, or a fix that does
    not verify all end in `escalate` (a human looks), never in a guess;
  - production is never touched: the report carries the production SQL for
    the action, to run only after a human approves it.
Every model turn and tool call is kept in the run transcript.

Usage: python -m glue.doctor --db MARKET_AGENT_CI_x   (after a failed check)
Env: GLUE_LOCAL_MODEL, OLLAMA_URL, SNOWFLAKE_CONNECTION (see glue/analyst.py),
DBT_PROFILES_DIR with a `ci` target whose database is $CI_DATABASE.
"""

import argparse
import json
import logging
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx
import snowflake.connector
import yaml
from pydantic import BaseModel

from cicd.snowflake_ci import run_checks
from glue.guardrails import GuardrailViolation, check_sql

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("glue.doctor")

MODEL = os.getenv("GLUE_LOCAL_MODEL", "qwen3:14b")
EMBED_MODEL = os.getenv("GLUE_EMBED_MODEL", "nomic-embed-text")
KEYWORD_WEIGHT = 0.3
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
CONNECTION = os.getenv("SNOWFLAKE_CONNECTION", "market_agent")
REPO = Path(__file__).resolve().parent.parent
CATALOG = REPO / "knowledge" / "problem_catalog.yaml"
DBT_DIR = REPO / "dbt"

MAX_STEPS = 8
SQL_ROW_CAP = 20
MODEL_OPTIONS = {"temperature": 0, "num_predict": 600, "num_ctx": 12288}
MODEL_TIMEOUT_S = 180

BAD_OHLC = "high < low OR high < GREATEST(open, close) OR low > LEAST(open, close)"

# The only changes the doctor can make. Written and reviewed by people; the
# model just picks one. {db} is the clone (or MARKET_AGENT in the report's
# production proposal, which a human runs after approval).
RUNBOOK = {
    "dedupe_silver_bars": {
        "when": "SILVER.BARS has repeated (symbol, bar_ts) rows, e.g. a connector replayed messages. "
                "Keeps the most recently updated copy of each bar, then rebuilds Gold.",
        # INSERT OVERWRITE, not CREATE OR REPLACE: replacing the table would drop its
        # grants (catalog E4).
        "sql": ["INSERT OVERWRITE INTO {db}.SILVER.BARS SELECT * FROM {db}.SILVER.BARS "
                "QUALIFY ROW_NUMBER() OVER (PARTITION BY symbol, bar_ts ORDER BY _updated_at DESC) = 1"],
        "rebuild": True,
    },
    "quarantine_bad_bars": {
        "when": "Some bars break OHLC rules (high below low/open/close, or low above open/close): bad prints. "
                "Moves them to SILVER.BARS_QUARANTINE for review, then rebuilds Gold.",
        "sql": ["CREATE TABLE IF NOT EXISTS {db}.SILVER.BARS_QUARANTINE LIKE {db}.SILVER.BARS",
                "INSERT INTO {db}.SILVER.BARS_QUARANTINE SELECT * FROM {db}.SILVER.BARS WHERE " + BAD_OHLC,
                "DELETE FROM {db}.SILVER.BARS WHERE " + BAD_OHLC],
        "rebuild": True,
    },
    "rebuild_gold": {
        "when": "Silver is correct but Gold is stale (Silver has rows Gold lacks) or Gold lost its row access "
                "policy. Re-runs dbt build; its post-hooks reattach the policy.",
        "sql": [],
        "rebuild": True,
    },
    "escalate": {
        "when": "The cause is upstream or unclear, or the only fix would change what the data means "
                "(for example shifting timestamps). Hands the diagnosis to a human; changes nothing.",
        "sql": [],
        "rebuild": False,
    },
}

SYSTEM = """You are the pipeline doctor for a Snowflake market-data pipeline (Silver -> dbt -> Gold).
Checks failed in the throwaway database {db}. Find the root cause and choose ONE runbook action.

How to work:
1. Investigate with run_sql (read-only SELECT; only these tables: {tables}). Look at the actual
   rows behind each failing check. Keep queries small.
2. Use search_catalog with words describing what you saw in the data (not the check's name) to
   find the matching known problem. Cite only an ID that a search returned.
3. Call submit_diagnosis exactly once, with the catalog problem ID, the root cause, the evidence
   you saw, and the action. Pick the least drastic action that fixes the cause.

Base the root cause only on what your queries showed; if the data doesn't show why, say so.
Facts: timestamps are UTC (TIMESTAMP_NTZ); the regular session is 13:30-19:59 UTC. One bar =
one symbol per minute, so (symbol, bar_ts) must be unique. Gold.FCT_BARS is built from
Silver.BARS and must have the same row count; FCT_BARS and FCT_TRADES must carry
DELAYED_DATA_POLICY.

Runbook actions:
{runbook}

Failing checks:
{failures}

dbt build:
{dbt}

Table columns:
{schema}"""

TOOLS = [
    {"type": "function", "function": {
        "name": "run_sql", "description": "Run one read-only SELECT on the clone. Returns at most 20 rows.",
        "parameters": {"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]}}},
    {"type": "function", "function": {
        "name": "search_catalog", "description": "Search the catalog of known pipeline problems by keywords.",
        "parameters": {"type": "object", "properties": {"keywords": {"type": "string"}}, "required": ["keywords"]}}},
    {"type": "function", "function": {
        "name": "submit_diagnosis", "description": "Final answer: diagnosis and the one runbook action to take.",
        "parameters": {"type": "object", "required": ["problem_id", "root_cause", "evidence", "action"], "properties": {
            "problem_id": {"type": "string", "description": "Catalog ID, e.g. C1"},
            "root_cause": {"type": "string"},
            "evidence": {"type": "string", "description": "What the queries showed, with numbers"},
            "action": {"type": "string", "enum": list(RUNBOOK)}}}}},
]


class Diagnosis(BaseModel):
    problem_id: str = ""
    root_cause: str = ""
    evidence: str = ""
    action: str = "escalate"


class DoctorReport(BaseModel):
    database: str
    failing_checks: list[str]
    diagnosis: Diagnosis | None = None
    decided_by: str = "model"          # model | guardrail (budget, invalid action, failed verify)
    applied_sql: list[str] = []
    verified: bool | None = None       # checks pass after the fix (None: nothing applied)
    checks_after: list[str] = []
    production_proposal: list[str] = []
    needs_human: bool = True
    steps: int = 0
    tool_calls: dict[str, int] = {}
    guardrail_blocks: int = 0
    latency_s: float = 0.0
    model: str = MODEL
    transcript: list[dict] = []


def load_catalog() -> list[dict]:
    data = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    return [p for stage in data["stages"] for p in stage["problems"]]


class CatalogIndex:
    """Hybrid search over the problem catalog: local embeddings (nomic-embed-text
    on Ollama) plus IDF-weighted keywords. Found in the first evaluation: plain
    keyword counting ranked "Trades don't match bars" above "Duplicates after a
    connector restart" for "duplicate bars", because common words like "bars"
    counted as much as rare ones, and the model then cited the wrong problem."""

    def __init__(self, problems: list[dict]):
        self.problems = problems
        self.docs = [f"{p['title']}. {p['symptom']} {p['solution']}" for p in problems]
        self.tokens = [_tokens(d) for d in self.docs]
        df: dict[str, int] = {}
        for toks in self.tokens:
            for w in toks:
                df[w] = df.get(w, 0) + 1
        self.idf = {w: math.log(len(self.docs) / c) for w, c in df.items()}
        self.vectors = _embed([f"search_document: {d}" for d in self.docs])

    def search(self, query: str, top: int = 5) -> list[dict]:
        q_vec = _embed([f"search_query: {query}"])[0]
        q_tok = _tokens(query)
        kw = [sum(self.idf.get(w, 0) for w in q_tok & toks) for toks in self.tokens]
        kw_max = max(kw) or 1
        scores = [sum(a * b for a, b in zip(q_vec, v)) + KEYWORD_WEIGHT * k / kw_max
                  for v, k in zip(self.vectors, kw)]
        best = sorted(range(len(scores)), key=lambda i: -scores[i])[:top]
        return [{k: self.problems[i][k] for k in ("id", "title", "symptom", "solution")} for i in best]


def _tokens(text: str) -> set[str]:
    return {w.rstrip("s") for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2}


def _embed(texts: list[str]) -> list[list[float]]:
    resp = httpx.post(f"{OLLAMA_URL}/api/embed", timeout=MODEL_TIMEOUT_S,
                      json={"model": EMBED_MODEL, "input": texts})
    resp.raise_for_status()
    out = []
    for v in resp.json()["embeddings"]:
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        out.append([x / n for x in v])
    return out


def dbt_build(db: str) -> tuple[bool, str]:
    """Run dbt build --target ci against the clone; return (ok, short failure summary)."""
    env = {**os.environ, "CI_DATABASE": db}
    proc = subprocess.run([sys.executable, "-m", "dbt.cli.main", "build", "--target", "ci"], cwd=DBT_DIR, env=env,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        results = json.loads((DBT_DIR / "target" / "run_results.json").read_text(encoding="utf-8"))["results"]
        bad = [f"{r['unique_id'].split('.')[-1]}: {r['status']} ({(r.get('message') or '')[:120]})"
               for r in results if r["status"] not in ("success", "pass")]
    except (OSError, KeyError, ValueError):
        bad = [proc.stdout[-400:]]
    return proc.returncode == 0, ("all models and tests passed" if not bad else "\n".join(bad))


class PipelineDoctor:
    def __init__(self, db: str, connection: str = CONNECTION):
        if not db.startswith("MARKET_AGENT_CI_"):
            raise ValueError("the doctor only works on throwaway MARKET_AGENT_CI_* databases")
        self.db = db
        self.conn = snowflake.connector.connect(connection_name=connection)
        self.catalog = CatalogIndex(load_catalog())
        self.allowed = frozenset(f"{db}.{s}.{t}" for s, t in (
            ("SILVER", "BARS"), ("SILVER", "TRADES"), ("SILVER", "SYMBOLS"), ("SILVER", "NEWS"),
            ("GOLD", "FCT_BARS"), ("GOLD", "FCT_TRADES"), ("GOLD", "DIM_SYMBOLS"), ("GOLD", "DIM_DATE")))

    def failing(self) -> list[str]:
        return [f"{name}: {detail}" for name, ok, detail in run_checks(self.conn.cursor(), self.db) if not ok]

    def _schema(self) -> str:
        rows = self.conn.cursor().execute(f"""SELECT table_schema || '.' || table_name, LISTAGG(column_name, ', ')
            WITHIN GROUP (ORDER BY ordinal_position) FROM {self.db}.INFORMATION_SCHEMA.COLUMNS
            WHERE table_schema IN ('SILVER', 'GOLD') AND table_name IN ('BARS', 'TRADES', 'FCT_BARS', 'FCT_TRADES')
            GROUP BY 1 ORDER BY 1""").fetchall()
        return "\n".join(f"{self.db}.{t}({c.lower()})" for t, c in rows)

    def _run_sql(self, sql: str) -> tuple[str, bool]:
        try:
            checked = check_sql(sql, row_limit=SQL_ROW_CAP, allowed_tables=self.allowed)
        except GuardrailViolation as v:
            return f"REFUSED by guardrail ({v.code}): {v.reason}", True
        try:
            cur = self.conn.cursor().execute(checked.sql)
        except snowflake.connector.errors.ProgrammingError as e:
            return f"SQL error: {str(e).splitlines()[0]}", False
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        return json.dumps({"columns": cols, "rows": [[str(v) for v in r] for r in rows]}), False

    def _chat(self, messages: list[dict]) -> dict:
        for attempt in range(2):
            try:
                resp = httpx.post(f"{OLLAMA_URL}/api/chat", timeout=MODEL_TIMEOUT_S, json={
                    "model": MODEL, "messages": messages, "tools": TOOLS, "stream": False,
                    "think": False, "options": MODEL_OPTIONS})
                resp.raise_for_status()
                return resp.json()["message"]
            except httpx.TimeoutException:
                if attempt:
                    raise

    def diagnose(self, failures: list[str], dbt_summary: str, report: DoctorReport) -> Diagnosis | None:
        runbook = "\n".join(f"- {name}: {a['when']}" for name, a in RUNBOOK.items())
        messages = [{"role": "system", "content": SYSTEM.format(
            db=self.db, tables=", ".join(sorted(self.allowed)), runbook=runbook,
            failures="\n".join(f"- {f}" for f in failures), dbt=dbt_summary, schema=self._schema())},
            {"role": "user", "content": "Investigate and submit your diagnosis."}]
        seen_ids: set[str] = set()
        for step in range(1, MAX_STEPS + 1):
            report.steps = step
            msg = self._chat(messages)
            messages.append({k: msg[k] for k in ("role", "content", "tool_calls") if k in msg})
            report.transcript.append({"step": step, "model": msg.get("content", ""),
                                      "tool_calls": msg.get("tool_calls", [])})
            calls = msg.get("tool_calls") or []
            if not calls:
                messages.append({"role": "user", "content": "Use a tool. Call submit_diagnosis when you know the cause."})
                continue
            for call in calls:
                name, args = call["function"]["name"], call["function"].get("arguments") or {}
                report.tool_calls[name] = report.tool_calls.get(name, 0) + 1
                if name == "submit_diagnosis":
                    dx = Diagnosis(**{k: str(v) for k, v in args.items() if k in Diagnosis.model_fields})
                    # Found in the first evaluation: the model cited a catalog ID that no
                    # search had returned. A diagnosis must cite a problem it actually read.
                    if dx.problem_id.strip() not in seen_ids and step < MAX_STEPS:
                        report.guardrail_blocks += 1
                        result = (f"Rejected: {dx.problem_id!r} was not in any search_catalog result. Search the "
                                  f"catalog for the symptom you saw, then cite one of the IDs it returns.")
                        report.transcript.append({"step": step, "tool": name, "args": args, "result": result})
                        messages.append({"role": "tool", "content": result, "tool_name": name})
                        continue
                    return dx
                if name == "run_sql":
                    result, blocked = self._run_sql(str(args.get("sql", "")))
                    report.guardrail_blocks += blocked
                elif name == "search_catalog":
                    hits = self.catalog.search(str(args.get("keywords", "")))
                    seen_ids.update(h["id"] for h in hits)
                    result = json.dumps(hits)
                else:
                    result = f"Unknown tool {name}."
                report.transcript.append({"step": step, "tool": name, "args": args, "result": result[:1500]})
                messages.append({"role": "tool", "content": result[:4000], "tool_name": name})
        return None  # budget exhausted

    def run(self, dbt_summary: str = "not run") -> DoctorReport:
        start = time.time()
        failures = self.failing()
        report = DoctorReport(database=self.db, failing_checks=failures)
        if not failures:
            report.needs_human, report.decided_by = False, "checks"
            report.latency_s = round(time.time() - start, 1)
            return report

        dx = self.diagnose(failures, dbt_summary, report)
        if dx is None:
            dx, report.decided_by = Diagnosis(root_cause="step budget exhausted"), "guardrail"
        if dx.action not in RUNBOOK:
            dx.root_cause += f" (model asked for unknown action {dx.action!r})"
            dx.action, report.decided_by = "escalate", "guardrail"
        report.diagnosis = dx

        action = RUNBOOK[dx.action]
        if action["sql"] or action["rebuild"]:
            cur = self.conn.cursor()
            for stmt in action["sql"]:
                sql = stmt.format(db=self.db)
                if self.db not in sql or "MARKET_AGENT." in sql:  # clone only, never production
                    raise RuntimeError(f"refusing to run outside the clone: {sql}")
                cur.execute(sql)
                report.applied_sql.append(sql)
            if action["rebuild"]:
                ok, _ = dbt_build(self.db)
                report.applied_sql.append(f"dbt build --target ci  ({'passed' if ok else 'failed'})")
            report.checks_after = self.failing()
            report.verified = not report.checks_after
            report.production_proposal = [s.format(db="MARKET_AGENT") for s in action["sql"]] + (
                ["dbt build --target prod  (snowflake-cd.yml, approval-gated)"] if action["rebuild"] else [])
            if not report.verified:
                report.decided_by = "guardrail"  # the fix didn't hold: a human decides
        report.needs_human = True  # always: production changes need approval; escalations need a person
        report.latency_s = round(time.time() - start, 1)
        return report


def render(report: DoctorReport) -> str:
    dx = report.diagnosis
    lines = [f"## Pipeline doctor report: `{report.database}`", "",
             "**Failing checks:**", *([f"- {f}" for f in report.failing_checks] or ["- none"]), ""]
    if dx:
        lines += [f"**Diagnosis:** catalog `{dx.problem_id}`, {dx.root_cause}", "",
                  f"**Evidence:** {dx.evidence}", "", f"**Action:** `{dx.action}` (decided by {report.decided_by})", ""]
    if report.applied_sql:
        lines += ["**Applied in the clone:**", "```sql", *report.applied_sql, "```",
                  f"**Verified:** {'yes, all checks pass' if report.verified else 'NO: ' + '; '.join(report.checks_after)}", ""]
    if report.production_proposal and report.verified:
        lines += ["**Proposed for production (runs only after human approval):**", "```sql",
                  *report.production_proposal, "```"]
    elif dx and dx.action == "escalate":
        lines += ["**Escalated:** no change made; a human takes it from this diagnosis."]
    lines += ["", f"_{report.steps} model steps, tools {report.tool_calls}, {report.guardrail_blocks} guardrail "
              f"blocks, {report.latency_s} s, model {report.model} (local)._"]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=os.environ.get("CI_DATABASE", ""))
    args = parser.parse_args()
    ok, dbt_summary = dbt_build(args.db)
    report = PipelineDoctor(args.db).run(dbt_summary)
    print(render(report))


if __name__ == "__main__":
    main()
