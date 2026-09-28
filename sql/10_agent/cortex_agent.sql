-- Step 6b: Cortex Agent -- orchestrates the two tools below (structured data
-- via the Semantic View, unstructured news via Cortex Search) behind one
-- entry point, instead of the app having to decide which to call. This is
-- what agent/cortex_agent_client.py and agent/mcp_server.py talk to.

CREATE SCHEMA IF NOT EXISTS MARKET_AGENT.AGENTS;

CREATE OR REPLACE AGENT MARKET_AGENT.AGENTS.MARKET_DATA_AGENT
  COMMENT = 'Answers questions over real-time market data and recent news, governed by the same Row Access Policy and role restrictions as the rest of this project.'
  FROM SPECIFICATION $$
{
  "instructions": {
    "response": "Answer using only the tools provided. For price/volume/return/volatility questions, use analyst. For 'what's happening with this stock' or news/sentiment questions, use search and cite the source URL. Never guess a number -- if analyst can't produce SQL for a question, say so rather than estimating.",
    "orchestration": "Prefer analyst for anything involving a number (price, volume, return, volatility). Prefer search for anything about why something happened or recent events. Some questions ('why did AAPL drop today') need both: pull the price move from analyst, then search for a news explanation."
  },
  "tools": [
    {
      "tool_spec": {
        "type": "cortex_analyst_text_to_sql",
        "name": "analyst",
        "description": "Answers quantitative questions about trades, bars, prices, volume, return, and volatility using the governed Semantic View."
      }
    },
    {
      "tool_spec": {
        "type": "cortex_search",
        "name": "search",
        "description": "Searches recent financial news for a symbol and returns cited excerpts."
      }
    }
  ],
  "tool_resources": {
    "analyst": {
      "semantic_view": "MARKET_AGENT.GOLD.MARKET_SEMANTIC_VIEW",
      "warehouse": "ANALYST_WH"
    },
    "search": {
      "name": "MARKET_AGENT.SILVER.NEWS_SEARCH_SERVICE",
      "max_results": 5,
      "id_column": "url"
    }
  }
}
$$;

GRANT USAGE ON SCHEMA MARKET_AGENT.AGENTS TO ROLE ANALYST_AGENT;
GRANT USAGE ON AGENT MARKET_AGENT.AGENTS.MARKET_DATA_AGENT TO ROLE ANALYST_AGENT;
