"""
Analyst glue agent: plain-English question -> SQL -> governed answer.

The flow is the plan in docs/glue-and-guardrails.md, built with existing pieces:
  1. A local model (Ollama, default qwen3:14b) proposes one SQL query over the
     Gold star schema. Local because Snowflake Cortex isn't available on trial
     accounts, and because it costs nothing and keeps data on this machine.
     The same code path can use Claude on Vertex AI later (glue/llm.py).
  2. glue/guardrails.py checks it: one read-only statement, Gold tables only,
     row cap. Anything else is refused before it reaches Snowflake.
  3. Snowflake runs it as ANALYST_AGENT with secondary roles off, on the
     agent's own small warehouse -- so the 15-minute delay policy and the
     30-second statement timeout apply no matter what the model wrote.
  4. Every question, refused or answered, is written to the append-only
     GOVERNANCE.AGENT_QUERY_AUDIT_LOG.

The model writes SQL but never states numbers: the answer returned is the
query result itself, so a number in an answer always came from executed SQL.

Usage: python -m glue.analyst "Which stock had the highest return?"
Env: GLUE_LOCAL_MODEL (default qwen3:14b), OLLAMA_URL (default
http://127.0.0.1:11434), SNOWFLAKE_CONNECTION (default market_agent).
"""

import argparse
import json
import logging
import os
import re
import time
import uuid

import httpx
import snowflake.connector
from pydantic import BaseModel

from glue.guardrails import ALLOWED_TABLES, GuardrailViolation, check_sql

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("glue.analyst")

MODEL = os.getenv("GLUE_LOCAL_MODEL", "qwen3:14b")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
CONNECTION = os.getenv("SNOWFLAKE_CONNECTION", "market_agent")

# Found in the first evaluation run: without an output cap the local model can
# loop inside the JSON format until the HTTP timeout (3-12 minutes per
# question), or return truncated JSON. A cap plus one retry fixes both.
MODEL_OPTIONS = {"temperature": 0, "num_predict": 700, "num_ctx": 8192}
MODEL_TIMEOUT_S = 90

# Guardrail codes that mean "badly formatted", worth one corrected attempt.
# Policy violations (writes, privilege changes, ungoverned tables) are refused
# outright and never retried.
RETRYABLE_GUARDRAIL_CODES = {"MULTIPLE_STATEMENTS", "UNPARSEABLE", "EMPTY"}

BUSINESS_RULES = """\
- All timestamps are UTC (TIMESTAMP_NTZ). One FCT_BARS row = one symbol, one minute;
  the regular session is 13:30-19:59 UTC (9:30-16:00 US/Eastern).
- date_key is the UTC date (TIMESTAMP_NTZ at midnight).
- Session return for a symbol = (close of its last bar - open of its first bar) / open of its first bar.
  Use MAX_BY(close, bar_ts) and MIN_BY(open, bar_ts).
- bar_return is the one-minute return of a bar; volatility = STDDEV(bar_return) unless asked otherwise.
- rolling_volatility_30 is the trailing 30-bar stddev of bar_return; is_suspect flags a >10% one-minute move.
- Intraday range % for a symbol = (MAX(high) - MIN(low)) / MIN(low), over all its bars.
- FCT_TRADES has one row per trade; notional = price * size. Sector lives in DIM_SYMBOLS.
- Data may be delayed 15 minutes by policy; never assume rows newer than that exist."""

SYSTEM = """You translate questions about U.S. equities market data into ONE Snowflake SQL query.
Rules:
- Output a single read-only SELECT (CTEs allowed). Never modify data or change roles/sessions.
- Use only these fully qualified tables: {tables}
- If the question cannot be answered from these tables, or asks you to change data, roles or
  privileges, reply with exactly: UNANSWERABLE
- Otherwise reply with only the SQL inside a ```sql code block. Return the columns needed to
  answer, with clear aliases. Do not invent numbers.

Schema:
{schema}

Business rules:
{rules}

Data available right now:
{facts}"""

# Found in evaluation: with JSON-constrained output, the local model wrote correct
# SQL and then leaked stray characters and its "</think>" tag into the JSON,
# breaking it whenever the SQL contained a quote. Plain text with a fenced
# code block is far more reliable for small local models. The extracted text
# still goes through glue/guardrails.py unchanged, so this affects parsing
# only, never what is allowed to run.
_CODE_BLOCK = re.compile(r"```(?:sql)?\s*(.*?)```", re.S | re.I)
_THINK = re.compile(r"<think>.*?</think>|</?think>", re.S | re.I)


def extract_sql(text: str) -> str | None:
    """Return the proposed SQL, or None if the model declined."""
    text = _THINK.sub("", text or "").strip()
    block = _CODE_BLOCK.search(text)
    if block:
        return block.group(1).strip()
    if re.fullmatch(r"\W*UNANSWERABLE\W*", text, re.I):
        return None
    start = re.search(r"\b(SELECT|WITH)\b", text, re.I)
    return text[start.start():].strip() if start else None


class AnalystAnswer(BaseModel):
    question: str
    status: str                      # answered | refused | unanswerable | error
    sql: str | None = None           # the statement actually executed (row cap applied)
    columns: list[str] = []
    rows: list[list] = []
    row_count: int = 0
    explanation: str = ""
    guardrail_code: str | None = None
    error: str | None = None
    as_of_utc: str | None = None
    latency_s: float = 0.0
    model: str = MODEL
    request_id: str = ""


class AnalystAgent:
    def __init__(self, connection: str = CONNECTION):
        self.conn = snowflake.connector.connect(connection_name=connection)
        cur = self.conn.cursor()
        # Act strictly as the agent's role: no secondary roles, its own warehouse.
        for stmt in ("USE ROLE ANALYST_AGENT", "USE SECONDARY ROLES NONE", "USE WAREHOUSE ANALYST_WH"):
            cur.execute(stmt)
        self.schema = self._describe_schema()
        self.facts = self._describe_data()

    def _describe_schema(self) -> str:
        rows = self.conn.cursor().execute("""
            SELECT table_name, column_name, data_type
            FROM MARKET_AGENT.INFORMATION_SCHEMA.COLUMNS
            WHERE table_schema = 'GOLD' AND table_name IN ('FCT_BARS', 'FCT_TRADES', 'DIM_SYMBOLS', 'DIM_DATE')
            ORDER BY table_name, ordinal_position""").fetchall()
        tables: dict[str, list[str]] = {}
        for t, c, d in rows:
            tables.setdefault(f"MARKET_AGENT.GOLD.{t}", []).append(f"{c.lower()} {d}")
        return "\n".join(f"{t}({', '.join(cols)})" for t, cols in tables.items())

    def _describe_data(self) -> str:
        """Ground the model in what the data actually covers. Found in evaluation:
        without this, the model read "the session" as CURRENT_DATE and returned no
        rows (catalog problem F1, ambiguous "today")."""
        first, last, days, symbols = self.conn.cursor().execute("""
            SELECT MIN(date_key)::DATE, MAX(date_key)::DATE, COUNT(DISTINCT date_key),
                   LISTAGG(DISTINCT symbol, ', ') WITHIN GROUP (ORDER BY symbol)
            FROM MARKET_AGENT.GOLD.FCT_BARS""").fetchone()
        return (f"- Trading dates in the data: {first} to {last} ({days} session(s)). Symbols: {symbols}.\n"
                f"- \"The session\" or \"today\" with no date means the latest date_key in the data "
                f"({last}); filter with date_key = (SELECT MAX(date_key) FROM MARKET_AGENT.GOLD.FCT_BARS) "
                f"or not at all. Never filter on CURRENT_DATE.\n"
                f"- Do not filter on is_suspect unless the question asks about flagged bars.")

    def _propose(self, question: str, feedback: str | None = None) -> dict:
        messages = [
            {"role": "system", "content": SYSTEM.format(
                tables=", ".join(sorted(ALLOWED_TABLES)), schema=self.schema, rules=BUSINESS_RULES,
                facts=self.facts)},
            {"role": "user", "content": question},
        ]
        if feedback:
            messages.append({"role": "user", "content": feedback})
        last_error = None
        for _ in range(2):  # one retry on a truncated reply or a timeout
            try:
                resp = httpx.post(f"{OLLAMA_URL}/api/chat", timeout=MODEL_TIMEOUT_S, json={
                    "model": MODEL, "messages": messages, "stream": False, "think": False,
                    "options": MODEL_OPTIONS,
                })
                resp.raise_for_status()
                content = resp.json()["message"]["content"]
                sql = extract_sql(content)
                return {"answerable": sql is not None, "sql": sql or "", "explanation": ""}
            except httpx.TimeoutException as e:
                last_error = e
        raise last_error

    def _audit(self, question: str, sql: str | None, request_id: str, ambiguous: bool) -> None:
        self.conn.cursor().execute(
            "INSERT INTO MARKET_AGENT.GOVERNANCE.AGENT_QUERY_AUDIT_LOG (question, generated_sql, request_id, is_ambiguous)"
            " VALUES (%s, %s, %s, %s)", (question, sql, request_id, ambiguous))

    def ask(self, question: str) -> AnalystAnswer:
        start, request_id = time.time(), str(uuid.uuid4())
        answer = AnalystAnswer(question=question, status="error", request_id=request_id)
        feedback = None
        try:
            for attempt in range(3):  # repair attempts for Snowflake errors or badly formatted SQL
                proposal = self._propose(question, feedback)
                answer.explanation = proposal.get("explanation", "")
                if not proposal.get("answerable") or not proposal.get("sql", "").strip():
                    answer.status = "unanswerable"
                    break
                try:
                    checked = check_sql(proposal["sql"])
                except GuardrailViolation as v:
                    answer.status, answer.guardrail_code, answer.error = "refused", v.code, v.reason
                    answer.sql = proposal["sql"]
                    if v.code in RETRYABLE_GUARDRAIL_CODES and attempt < 2:
                        feedback = f"Rejected: {v.reason}. Return exactly one SELECT statement and nothing else."
                        continue
                    break
                try:
                    cur = self.conn.cursor().execute(checked.sql)
                except snowflake.connector.errors.ProgrammingError as e:
                    feedback = f"That SQL failed in Snowflake: {str(e).splitlines()[0]}. Return a corrected query."
                    answer.error = str(e).splitlines()[0]
                    continue
                answer.sql = checked.sql
                answer.columns = [d[0] for d in cur.description]
                rows = cur.fetchall()
                answer.rows = [[v if isinstance(v, (int, float, str, type(None))) else str(v) for v in r] for r in rows[:50]]
                answer.row_count = len(rows)
                answer.as_of_utc = str(self.conn.cursor().execute("SELECT SYSDATE()").fetchone()[0])
                answer.status, answer.error = "answered", None
                break
        except Exception as e:  # model or network failure: report it, don't guess
            answer.status, answer.error = "error", f"{type(e).__name__}: {e}"
        answer.latency_s = round(time.time() - start, 2)
        self._audit(question, answer.sql, request_id, answer.status != "answered")
        return answer


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("question")
    args = parser.parse_args()
    a = AnalystAgent().ask(args.question)
    print(json.dumps(a.model_dump(), indent=2, default=str))


if __name__ == "__main__":
    main()
