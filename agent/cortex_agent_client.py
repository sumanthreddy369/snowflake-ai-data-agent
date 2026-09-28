"""
REST wrapper around the Cortex Agent created in sql/10_agent/cortex_agent.sql
(POST /api/v2/databases/{db}/schemas/{schema}/agents/{name}:run). Unlike
cortex_client.py (which calls Cortex Analyst directly for a single
structured-data question), this calls the Agent, which can choose between the
analyst tool (Semantic View) and the search tool (Cortex Search over news) --
or both -- per question.

The API streams server-sent events by default; this client sets stream=false
for a single JSON response, which is simpler to trace through Langfuse and
log to the audit table.

Env vars: same as cortex_client.py, plus none new -- reuses
SNOWFLAKE_ACCOUNT_HOST, SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_PAT.
"""

import argparse
import logging
import os

import httpx
from langfuse import observe
from tenacity import retry, stop_after_attempt, wait_exponential

from cortex_client import _write_audit_log, _headers
from schemas import AgentRunResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("cortex_agent_client")

AGENT_DATABASE = "MARKET_AGENT"
AGENT_SCHEMA = "AGENTS"
AGENT_NAME = "MARKET_DATA_AGENT"


@retry(wait=wait_exponential(multiplier=1, min=2, max=20), stop=stop_after_attempt(3))
def _run_agent(host: str, payload: dict) -> httpx.Response:
    url = f"https://{host}/api/v2/databases/{AGENT_DATABASE}/schemas/{AGENT_SCHEMA}/agents/{AGENT_NAME}:run"
    resp = httpx.post(url, json=payload, headers=_headers(), timeout=90.0)
    resp.raise_for_status()
    return resp


@observe(name="cortex-agent-run", as_type="generation")
def ask_market_data_agent(question: str) -> AgentRunResponse:
    payload = {
        "messages": [{"role": "user", "content": [{"type": "text", "text": question}]}],
        "stream": False,
    }
    resp = _run_agent(os.environ["SNOWFLAKE_ACCOUNT_HOST"], payload)
    body = resp.json()

    content = body.get("message", {}).get("content", [])
    text = next((c["text"] for c in content if c.get("type") == "text"), None)
    tool_uses = [c for c in content if c.get("type") == "tool_use"]
    tool_results = [c for c in content if c.get("type") == "tool_result"]
    sql = next(
        (
            tr.get("content", {}).get("sql")
            for tr in tool_results
            if tr.get("content", {}).get("sql")
        ),
        None,
    )
    citations = [
        {"url": tr["content"].get("url"), "headline": tr["content"].get("headline")}
        for tr in tool_results
        if tr.get("type") == "tool_result" and tr.get("content", {}).get("url")
    ]

    result = AgentRunResponse(
        request_id=resp.headers.get("X-Snowflake-Request-Id"),
        text=text,
        sql=sql,
        tools_used=[t.get("name") for t in tool_uses],
        citations=citations,
    )
    # Reuse the same append-only audit log as the direct Analyst client --
    # every question asked of either entry point ends up in one place.
    _write_audit_log(question, result.sql, result.request_id)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question")
    args = parser.parse_args()
    print(ask_market_data_agent(args.question).model_dump_json(indent=2))


if __name__ == "__main__":
    main()
