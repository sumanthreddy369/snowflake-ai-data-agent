-- Native Semantic View -- the object Cortex Agents and the Snowflake-managed
-- MCP server actually consume (they don't read the YAML semantic model file;
-- that file is what the direct Cortex Analyst REST API in agent/cortex_client.py
-- uses). Both exist deliberately: the YAML model carries the richer custom
-- metrics (period_return, volatility via window functions -- see
-- semantic_model.yaml's comments on why those need MAX_BY/MIN_BY logic that's
-- awkward to express as a plain semantic-view METRIC), while this Semantic
-- View is the simpler, standard aggregation surface that Cortex Agents'
-- cortex_analyst_text_to_sql tool queries against.

CREATE OR REPLACE SEMANTIC VIEW MARKET_AGENT.GOLD.MARKET_SEMANTIC_VIEW
  TABLES (
    bars AS MARKET_AGENT.GOLD.FCT_BARS
      PRIMARY KEY (symbol, bar_ts)
      WITH SYNONYMS ('price bars', 'ohlc bars', 'minute bars')
      COMMENT = 'Minute-level OHLCV bars, one row per symbol per minute',
    trades AS MARKET_AGENT.GOLD.FCT_TRADES
      PRIMARY KEY (trade_id)
      WITH SYNONYMS ('trade prints', 'executions')
      COMMENT = 'Individual trade prints',
    symbols AS MARKET_AGENT.GOLD.DIM_SYMBOLS
      PRIMARY KEY (symbol)
      WITH SYNONYMS ('tickers', 'stocks', 'companies')
      COMMENT = 'Symbol reference data'
  )
  RELATIONSHIPS (
    bars_to_symbols AS bars (symbol) REFERENCES symbols,
    trades_to_symbols AS trades (symbol) REFERENCES symbols
  )
  FACTS (
    bars.open_price AS open,
    bars.high_price AS high,
    bars.low_price AS low,
    bars.close_price AS close,
    bars.bar_volume AS volume,
    bars.bar_return_pct AS bar_return,
    bars.rolling_volatility AS rolling_volatility_30,
    trades.trade_price AS price,
    trades.trade_size AS size,
    trades.trade_notional AS notional
  )
  DIMENSIONS (
    symbols.ticker AS symbol WITH SYNONYMS ('stock symbol', 'ticker symbol'),
    symbols.company AS company_name,
    symbols.sector_name AS sector,
    symbols.exchange_name AS exchange,
    bars.bar_date AS date_key,
    bars.is_flagged AS is_suspect
      COMMENT = 'True when a bar moved more than 10% in one minute -- a circuit-breaker flag, not an automatic exclusion. See sql/09_guardrails.',
    trades.exchange_code AS exchange_code
  )
  METRICS (
    bars.total_volume AS SUM(bars.bar_volume)
      COMMENT = 'Total shares traded across the filtered bars',
    bars.avg_close_price AS AVG(bars.close_price)
      COMMENT = 'Average closing price across the filtered bars',
    bars.avg_volatility AS AVG(bars.rolling_volatility)
      COMMENT = 'Average of each bar''s trailing 30-bar return standard deviation',
    trades.trade_count AS COUNT(trades.price)
      COMMENT = 'Number of trade prints',
    trades.total_notional_value AS SUM(trades.notional)
      COMMENT = 'Total dollar value traded across the filtered trades',
    trades.avg_trade_size AS AVG(trades.size)
  );

-- Grant usage the same way sql/07_governance grants SELECT on the underlying
-- Gold tables -- the Row Access Policy on FCT_BARS/FCT_TRADES still applies
-- when queried through this Semantic View, since it's enforced at the table
-- level, not bypassed by going through a view.
GRANT SELECT ON SEMANTIC VIEW MARKET_AGENT.GOLD.MARKET_SEMANTIC_VIEW TO ROLE ANALYST_AGENT;
GRANT SELECT ON SEMANTIC VIEW MARKET_AGENT.GOLD.MARKET_SEMANTIC_VIEW TO ROLE BI_READER;
