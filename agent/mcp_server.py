"""
A small MCP server exposing this project's governed data access as tools any
MCP-aware client (Claude, another agent, etc.) can call -- the "MCP" step in
the architecture: Cortex Agents -> MCP -> AI Data Assistant. This is a
custom, standalone MCP server (FastMCP) rather than Snowflake's own managed
MCP server (a Native Apps feature, GA August 2026, that would require
packaging this whole project as a Snowflake Native App) -- a reasonable,
independently runnable substitute that wraps the same governed clients.

None of the three tools below bypass governance: ask_market_data and
search_market_news go through the Cortex Agent / Cortex Search, which query
through ANALYST_AGENT and are subject to the Row Access Policy and the
15-minute-delayed-data rule exactly as they would from Snowsight. There is no
"admin" tool here with broader access.

Run: python mcp_server.py  (stdio transport, for a local MCP client)
"""

import logging

from fastmcp import FastMCP

from cortex_agent_client import ask_market_data_agent
from cortex_client import ask_cortex_analyst

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("mcp_server")

mcp = FastMCP(name="market-data-agent")


@mcp.tool
def ask_market_data(question: str) -> str:
    """Ask a plain-English question about market data or recent news; the
    agent decides whether to query prices/volume/return/volatility, search
    news, or both. Answers are subject to a 15-minute delayed-data policy --
    this tool can never return a true real-time price.
    """
    result = ask_market_data_agent(question)
    return result.model_dump_json(indent=2)


@mcp.tool
def ask_market_data_direct(question: str) -> str:
    """Ask a quantitative question directly against the Semantic Model
    (skips the agent's tool-routing decision) -- use this when you already
    know the question is purely about prices/volume/return/volatility.
    """
    result = ask_cortex_analyst(question)
    return result.model_dump_json(indent=2)


@mcp.tool
def get_flagged_anomalies(symbol: str | None = None) -> str:
    """Return today's circuit-breaker-flagged bars (>10% one-minute move) --
    see sql/09_guardrails and the is_suspect column on fct_bars. Optionally
    filter to one symbol. These are flagged for review, not necessarily bugs.
    """
    import os

    import snowflake.connector

    conn = snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PAT"],
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", "ANALYST_WH"),
        role=os.environ.get("SNOWFLAKE_ROLE", "ANALYST_AGENT"),
    )
    try:
        query = """
            SELECT symbol, bar_ts, open, close, bar_return
            FROM MARKET_AGENT.GOLD.FCT_BARS
            WHERE date_key = CURRENT_DATE() AND is_suspect
        """
        params = ()
        if symbol:
            query += " AND symbol = %s"
            params = (symbol,)
        query += " ORDER BY ABS(bar_return) DESC"

        cur = conn.cursor()
        cur.execute(query, params)
        rows = cur.fetchall()
        columns = [c[0] for c in cur.description]
        return str([dict(zip(columns, row)) for row in rows])
    finally:
        conn.close()


if __name__ == "__main__":
    mcp.run()
