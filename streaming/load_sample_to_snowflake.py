"""
Loads the checked-in sample CSVs (streaming/data/sample_*.csv) into the Bronze
tables in Snowflake, the same way a batch file would arrive: PUT to each
table's internal stage, then COPY INTO. No cloud bucket needed, so this is the
quickest way to get real rows into a fresh account.

The source file name is captured with METADATA$FILENAME inside the COPY
transformation -- the only place Snowflake exposes it -- into _source_file.

Connection: a named connection from ~/.snowflake/connections.toml (key-pair
auth, no password), default "market_agent". Prints rows loaded per table.
"""

import argparse
import logging
from pathlib import Path

import snowflake.connector

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("load_sample_to_snowflake")

DATA_DIR = Path(__file__).resolve().parent / "data"

# table -> (csv file, columns in file order)
TABLES = {
    "MARKET_AGENT.BRONZE.RAW_SYMBOLS": ("sample_symbols.csv",
                                        ["symbol", "company_name", "sector", "exchange", "is_active"]),
    "MARKET_AGENT.BRONZE.RAW_BARS": ("sample_bars.csv",
                                     ["symbol", "bar_ts", "open", "high", "low", "close", "volume", "vwap",
                                      "trade_count"]),
    "MARKET_AGENT.BRONZE.RAW_TRADES": ("sample_trades.csv",
                                       ["trade_id", "symbol", "price", "size", "exchange_code", "conditions",
                                        "trade_ts"]),
    "MARKET_AGENT.BRONZE.RAW_NEWS": ("sample_news.csv",
                                     ["news_id", "headline", "summary", "content", "symbols", "source", "url",
                                      "published_at"]),
}

FILE_FORMAT = "TYPE = CSV SKIP_HEADER = 1 FIELD_OPTIONALLY_ENCLOSED_BY = '\"' NULL_IF = ('', 'NULL')"


def load(conn, table: str, csv_name: str, columns: list[str]) -> int:
    path = (DATA_DIR / csv_name).as_posix()
    cur = conn.cursor()
    cur.execute(f"PUT 'file://{path}' @%{table.split('.')[-1]} OVERWRITE = TRUE AUTO_COMPRESS = TRUE")
    select = ", ".join(f"${i + 1}" for i in range(len(columns)))
    result = cur.execute(
        f"COPY INTO {table} ({', '.join(columns)}, _source_file) "
        f"FROM (SELECT {select}, METADATA$FILENAME FROM @%{table.split('.')[-1]}) "
        f"FILE_FORMAT = ({FILE_FORMAT}) ON_ERROR = ABORT_STATEMENT"
    ).fetchall()
    loaded = sum(int(row[3]) for row in result if len(row) > 3 and str(row[3]).isdigit())
    logger.info("%s <- %s: %d rows", table, csv_name, loaded)
    return loaded


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--connection", default="market_agent")
    args = parser.parse_args()
    with snowflake.connector.connect(connection_name=args.connection) as conn:
        conn.cursor().execute("USE SCHEMA MARKET_AGENT.BRONZE")
        for table, (csv_name, columns) in TABLES.items():
            # PUT on a table stage needs the current schema to resolve @%TABLE.
            load(conn, table, csv_name, columns)


if __name__ == "__main__":
    main()
