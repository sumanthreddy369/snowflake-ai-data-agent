"""Unit tests for glue/guardrails.py -- no Snowflake or model needed."""

import pytest

from glue.guardrails import ALLOWED_TABLES, GuardrailViolation, check_sql


@pytest.mark.parametrize("sql", [
    "SELECT symbol, SUM(volume) FROM MARKET_AGENT.GOLD.FCT_BARS GROUP BY symbol",
    "select * from market_agent.gold.dim_symbols",
    """WITH r AS (SELECT symbol, bar_return FROM MARKET_AGENT.GOLD.FCT_BARS)
       SELECT symbol, STDDEV(bar_return) FROM r GROUP BY symbol""",
    """SELECT b.symbol, s.sector FROM MARKET_AGENT.GOLD.FCT_BARS b
       JOIN MARKET_AGENT.GOLD.DIM_SYMBOLS s ON s.symbol = b.symbol
       QUALIFY ROW_NUMBER() OVER (PARTITION BY b.symbol ORDER BY b.bar_ts DESC) = 1""",
    "SELECT COUNT(*) FROM MARKET_AGENT.GOLD.FCT_TRADES;",
    # A keyword inside a string literal is data, not an operation.
    "SELECT 'DROP TABLE x' AS note, COUNT(*) FROM MARKET_AGENT.GOLD.FCT_BARS",
])
def test_allows_read_only_gold_queries(sql):
    checked = check_sql(sql)
    assert checked.sql.startswith("SELECT * FROM (")
    assert checked.sql.rstrip().endswith("LIMIT 1000")
    assert set(checked.tables) <= ALLOWED_TABLES


@pytest.mark.parametrize("sql, code", [
    ("DELETE FROM MARKET_AGENT.GOLD.FCT_TRADES WHERE symbol = 'TSLA'", "NOT_READ_ONLY"),
    ("DROP TABLE MARKET_AGENT.GOLD.FCT_BARS", "NOT_READ_ONLY"),
    ("UPDATE MARKET_AGENT.GOLD.FCT_BARS SET close = 0", "NOT_READ_ONLY"),
    ("INSERT INTO MARKET_AGENT.GOLD.FCT_BARS SELECT * FROM MARKET_AGENT.GOLD.FCT_BARS", "NOT_READ_ONLY"),
    ("GRANT ROLE REALTIME_DESK TO ROLE ANALYST_AGENT", "NOT_READ_ONLY"),
    ("USE ROLE REALTIME_DESK", "NOT_READ_ONLY"),
    ("CREATE TABLE MARKET_AGENT.GOLD.X AS SELECT 1", "NOT_READ_ONLY"),
    # Stacked statements: the second one would escalate privileges.
    ("SELECT 1 FROM MARKET_AGENT.GOLD.FCT_BARS; USE ROLE REALTIME_DESK", "MULTIPLE_STATEMENTS"),
    # Raw and intermediate layers bypass the governed model.
    ("SELECT * FROM MARKET_AGENT.BRONZE.RAW_TRADES", "TABLE_NOT_ALLOWED"),
    ("SELECT * FROM MARKET_AGENT.SILVER.BARS", "TABLE_NOT_ALLOWED"),
    ("SELECT * FROM MARKET_AGENT.GOVERNANCE.AGENT_QUERY_AUDIT_LOG", "TABLE_NOT_ALLOWED"),
    ("SELECT * FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY", "TABLE_NOT_ALLOWED"),
    # Unqualified names could resolve anywhere in the session's context.
    ("SELECT * FROM FCT_BARS", "TABLE_NOT_ALLOWED"),
    ("SELECT CURRENT_ROLE()", "NO_ALLOWED_TABLE"),
    ("", "EMPTY"),
])
def test_blocks_unsafe_sql(sql, code):
    with pytest.raises(GuardrailViolation) as err:
        check_sql(sql)
    assert err.value.code == code


def test_cte_names_are_not_mistaken_for_tables():
    checked = check_sql("WITH fct_bars AS (SELECT * FROM MARKET_AGENT.GOLD.FCT_BARS) SELECT * FROM fct_bars")
    assert checked.tables == ("MARKET_AGENT.GOLD.FCT_BARS",)


def test_row_limit_is_configurable():
    assert check_sql("SELECT * FROM MARKET_AGENT.GOLD.FCT_BARS", row_limit=5).sql.endswith("LIMIT 5")
