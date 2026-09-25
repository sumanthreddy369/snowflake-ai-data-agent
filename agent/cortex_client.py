"""
Thin, observable wrapper around the Cortex Analyst REST API (Step 6 of the
pipeline). Cortex Analyst itself is a managed Snowflake product with no code
to write — this client exists so that every question asked of it is traced
through Langfuse (latency, the exact question, the SQL it generated) the same
way an LLM call in this project's companion Databricks project would be,
giving both projects the same observability story even though this one
doesn't hand-roll the agent.

Docs: https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst/rest-api

Auth: uses a Snowflake Programmatic Access Token (PAT) scoped to the
ANALYST_AGENT role (see sql/07_governance/rbac_and_masking.sql) — the role's
Row Access Policy is what actually keeps this client from ever seeing
real-time (sub-15-minute) prices, not anything in this code.

Env vars: SNOWFLAKE_ACCOUNT_HOST (e.g. "xy12345.snowflakecomputing.com"),
SNOWFLAKE_PAT, CORTEX_SEMANTIC_MODEL_FILE (stage path to semantic_model.yaml)
"""

import argparse
import os

import httpx
from langfuse import observe
from tenacity import retry, stop_after_attempt, wait_exponential

from schemas import CortexAnalystRequest, CortexAnalystResponse


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {os.environ['SNOWFLAKE_PAT']}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


@retry(wait=wait_exponential(multiplier=1, min=2, max=20), stop=stop_after_attempt(3))
def _post_message(host: str, payload: dict) -> httpx.Response:
    resp = httpx.post(
        f"https://{host}/api/v2/cortex/analyst/message",
        json=payload,
        headers=_headers(),
        timeout=60.0,
    )
    resp.raise_for_status()
    return resp


@observe(name="cortex-analyst-query", as_type="generation")
def ask_cortex_analyst(question: str) -> CortexAnalystResponse:
    request = CortexAnalystRequest(
        question=question,
        semantic_model_file=os.environ["CORTEX_SEMANTIC_MODEL_FILE"],
    )
    payload = {
        "messages": [{"role": "user", "content": [{"type": "text", "text": request.question}]}],
        "semantic_model_file": request.semantic_model_file,
    }

    resp = _post_message(os.environ["SNOWFLAKE_ACCOUNT_HOST"], payload)
    body = resp.json()
    request_id = resp.headers.get("X-Snowflake-Request-Id")

    content = body.get("message", {}).get("content", [])
    text = next((c["text"] for c in content if c.get("type") == "text"), None)
    sql = next((c["statement"] for c in content if c.get("type") == "sql"), None)
    suggestion = next((c for c in content if c.get("type") == "suggestion"), None)

    return CortexAnalystResponse(
        request_id=request_id,
        text=text,
        sql=sql,
        suggestions=suggestion.get("suggestions") if suggestion else None,
        is_ambiguous=suggestion is not None,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question")
    args = parser.parse_args()

    result = ask_cortex_analyst(args.question)
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
