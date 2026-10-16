"""
Snowflake steps for the GitHub Actions pipelines (snowflake-ci.yml, snowflake-cd.yml).

  clone   -- CI: create a throwaway database and zero-copy clone Silver into it,
             plus the delay policy dbt's post-hooks attach. Costs ~nothing:
             clones share storage with the source until something changes.
  checks  -- CI: after `dbt build` in the clone, verify governance and data
             (policy attached to both facts, Silver == Gold counts, no
             duplicates, OHLC rules, bars inside the session) and fail the job on any problem.
  drop    -- CI: remove the throwaway database (always runs).
  verify  -- CD: the same checks against the real MARKET_AGENT after deploy.

Each command appends a Markdown table to $GITHUB_STEP_SUMMARY, so results show
on the run page. Connection from env: SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER,
SNOWFLAKE_PRIVATE_KEY_PATH, SNOWFLAKE_ROLE, SNOWFLAKE_WAREHOUSE.
"""

import argparse
import logging
import os
import sys
import time

import snowflake.connector

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("snowflake_ci")

SILVER_TABLES = ("TRADES", "BARS", "SYMBOLS", "NEWS")
# Must match sql/07_governance/rbac_and_masking.sql.
POLICY_BODY = ("(row_ts TIMESTAMP_NTZ) RETURNS BOOLEAN -> "
               "CURRENT_ROLE() = 'REALTIME_DESK' OR row_ts <= DATEADD('minute', -15, SYSDATE())")


def connect():
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        authenticator="SNOWFLAKE_JWT",
        private_key_file=os.environ["SNOWFLAKE_PRIVATE_KEY_PATH"],
        role=os.environ["SNOWFLAKE_ROLE"],
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH"),
    )


def summary(lines: list[str]) -> None:
    text = "\n".join(lines) + "\n"
    print(text)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text + "\n")


def clone(db: str) -> None:
    start = time.time()
    with connect() as conn:
        cur = conn.cursor()
        cur.execute(f"CREATE OR REPLACE DATABASE {db} COMMENT = 'Throwaway CI database; dropped at end of run'")
        for schema in ("SILVER", "STAGING", "GOLD"):
            cur.execute(f"CREATE SCHEMA {db}.{schema}")
        rows = []
        for t in SILVER_TABLES:
            cur.execute(f"CREATE TABLE {db}.SILVER.{t} CLONE MARKET_AGENT.SILVER.{t}")
            n = cur.execute(f"SELECT COUNT(*) FROM {db}.SILVER.{t}").fetchone()[0]
            rows.append(f"| SILVER.{t} | {n:,} |")
        cur.execute(f"CREATE ROW ACCESS POLICY {db}.GOLD.DELAYED_DATA_POLICY AS {POLICY_BODY}")
    summary([f"### 1. Zero-copy clone `{db}` ({time.time() - start:.1f} s)", "",
             "| Cloned table | Rows |", "|---|---|", *rows, "",
             "Delay policy created in the clone so dbt's post-hooks can attach it."])


def run_checks(cur, db: str) -> list[tuple[str, bool, str]]:
    results = []
    for fact in ("FCT_TRADES", "FCT_BARS"):
        n = cur.execute(f"""SELECT COUNT(*) FROM TABLE({db}.INFORMATION_SCHEMA.POLICY_REFERENCES(
            ref_entity_name => '{db}.GOLD.{fact}', ref_entity_domain => 'table'))
            WHERE policy_name = 'DELAYED_DATA_POLICY'""").fetchone()[0]
        results.append((f"Delay policy attached to {fact}", n == 1, f"{n} reference(s)"))
    for silver, gold in (("BARS", "FCT_BARS"), ("TRADES", "FCT_TRADES"), ("SYMBOLS", "DIM_SYMBOLS")):
        s, g = cur.execute(f"SELECT (SELECT COUNT(*) FROM {db}.SILVER.{silver}),"
                           f" (SELECT COUNT(*) FROM {db}.GOLD.{gold})").fetchone()
        results.append((f"Silver.{silver} = Gold.{gold}", s == g and s > 0, f"{s:,} = {g:,}"))
    dupes, ohlc = cur.execute(f"""SELECT COUNT(*) - COUNT(DISTINCT symbol, bar_ts),
        COUNT_IF(high < low OR high < GREATEST(open, close) OR low > LEAST(open, close))
        FROM {db}.GOLD.FCT_BARS""").fetchone()
    results.append(("No duplicate (symbol, minute) bars", dupes == 0, f"{dupes} duplicates"))
    results.append(("OHLC rules hold", ohlc == 0, f"{ohlc} violations"))
    # Regular session is 13:30-19:59 UTC (9:30-16:00 US/Eastern). Bars outside
    # it usually mean a timezone bug upstream (catalog A9), not real trading.
    outside = cur.execute(f"""SELECT COUNT_IF(TO_TIME(bar_ts) NOT BETWEEN '13:30:00' AND '19:59:59')
        FROM {db}.GOLD.FCT_BARS""").fetchone()[0]
    results.append(("All bars inside the regular session (UTC)", outside == 0, f"{outside} outside"))
    return results


def report(title: str, results) -> int:
    failed = [r for r in results if not r[1]]
    summary([title, "", "| Check | Result | Detail |", "|---|---|---|",
             *[f"| {name} | {'✅ pass' if ok else '❌ FAIL'} | {detail} |" for name, ok, detail in results], "",
             f"**{len(results) - len(failed)}/{len(results)} checks passed.**"])
    return 1 if failed else 0


def checks(db: str) -> int:
    with connect() as conn:
        return report(f"### 3. Governance and data checks in `{db}`", run_checks(conn.cursor(), db))


def drop(db: str) -> None:
    with connect() as conn:
        conn.cursor().execute(f"DROP DATABASE IF EXISTS {db}")
    summary([f"### 4. Cleanup", "", f"Dropped `{db}`; production was never touched."])


def verify() -> int:
    with connect() as conn:
        return report("### 2. Post-deploy verification on `MARKET_AGENT` (production)",
                      run_checks(conn.cursor(), "MARKET_AGENT"))


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["clone", "checks", "drop", "verify"])
    parser.add_argument("--db", default=os.environ.get("CI_DATABASE", ""))
    args = parser.parse_args()
    if args.command in ("clone", "checks", "drop") and not args.db.startswith("MARKET_AGENT_CI_"):
        parser.error("--db must start with MARKET_AGENT_CI_ (a guard against touching production)")
    if args.command == "clone":
        clone(args.db)
    elif args.command == "checks":
        sys.exit(checks(args.db))
    elif args.command == "drop":
        drop(args.db)
    else:
        sys.exit(verify())


if __name__ == "__main__":
    main()
