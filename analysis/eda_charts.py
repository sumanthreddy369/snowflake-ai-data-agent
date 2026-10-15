"""
Draws the EDA charts from data queried live from Snowflake (MARKET_AGENT.GOLD),
for docs/snowflake-results.md. Snowsight's own charts are shown in the Snowsight
screenshots; these add the views that need more than one series per chart.

Connection: a named connection from ~/.snowflake/connections.toml (key-pair
auth), default "market_agent". Writes PNGs to docs/screenshots/snowflake/charts/.
"""

import argparse
import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
import snowflake.connector  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("eda_charts")

OUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "screenshots" / "snowflake" / "charts"
SOURCE = "Source: live query on Snowflake, MARKET_AGENT.GOLD"
COLORS = {"AAPL": "#2563eb", "AMZN": "#f59e0b", "GOOGL": "#10b981", "MSFT": "#ef4444", "TSLA": "#8b5cf6"}


def query(conn, sql: str) -> pd.DataFrame:
    cur = conn.cursor().execute(sql)
    return pd.DataFrame(cur.fetchall(), columns=[d[0].lower() for d in cur.description])


def finish(fig, ax, title: str, name: str) -> None:
    ax.set_title(title, loc="left", fontsize=13, fontweight="bold")
    ax.spines[["top", "right"]].set_visible(False)
    fig.text(0.01, 0.01, SOURCE, fontsize=8, color="#6b7280")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    path = OUT_DIR / f"{name}.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    logger.info("wrote %s", path)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--connection", default="market_agent")
    args = parser.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with snowflake.connector.connect(connection_name=args.connection) as conn:
        # 1. Price paths indexed to 100 at the open
        df = query(conn, """
            SELECT symbol, CONVERT_TIMEZONE('UTC', 'America/New_York', bar_ts) AS bar_et,
                   close / FIRST_VALUE(open) OVER (PARTITION BY symbol ORDER BY bar_ts) * 100 AS idx
            FROM MARKET_AGENT.GOLD.FCT_BARS ORDER BY symbol, bar_ts""")
        df["idx"] = df["idx"].astype(float)
        fig, ax = plt.subplots(figsize=(10, 5))
        for sym, g in df.groupby("symbol"):
            ax.plot(g["bar_et"], g["idx"], label=sym, color=COLORS.get(sym), linewidth=1.4)
        ax.axhline(100, color="#9ca3af", linewidth=0.8, linestyle="--")
        ax.set_ylabel("Price index (open = 100)")
        ax.set_xlabel("Time (US/Eastern)")
        ax.legend(ncol=5, frameon=False, loc="upper left")
        finish(fig, ax, "Intraday price path by stock, indexed to the open", "01-price-index")

        # 2. Volume and volatility by hour of the session
        df = query(conn, """
            SELECT HOUR(CONVERT_TIMEZONE('UTC', 'America/New_York', bar_ts)) AS hour_et,
                   SUM(volume) AS volume, AVG(rolling_volatility_30) * 1e4 AS vol_bps
            FROM MARKET_AGENT.GOLD.FCT_BARS GROUP BY 1 ORDER BY 1""")
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.bar(df["hour_et"].astype(str) + ":00", df["volume"].astype(float) / 1e6, color="#93c5fd", label="Volume (M shares)")
        ax.set_ylabel("Volume (million shares)")
        ax2 = ax.twinx()
        ax2.plot(df["hour_et"].astype(str) + ":00", df["vol_bps"].astype(float), color="#dc2626", marker="o",
                 label="Avg 30-bar volatility (bps)")
        ax2.set_ylabel("Volatility (basis points)")
        ax2.spines[["top"]].set_visible(False)
        ax.set_xlabel("Hour of session (US/Eastern; 9:00 = 9:30-10:00)")
        lines = ax.get_legend_handles_labels()[0] + ax2.get_legend_handles_labels()[0]
        labels = ax.get_legend_handles_labels()[1] + ax2.get_legend_handles_labels()[1]
        ax.legend(lines, labels, frameon=False, loc="upper left")
        finish(fig, ax, "Volume and volatility through the trading session", "02-volume-volatility-by-hour")

        # 3. Distribution of one-minute returns
        df = query(conn, "SELECT symbol, bar_return * 1e4 AS bps FROM MARKET_AGENT.GOLD.FCT_BARS WHERE bar_return IS NOT NULL")
        df["bps"] = df["bps"].astype(float)
        fig, ax = plt.subplots(figsize=(10, 5))
        syms = sorted(df["symbol"].unique())
        parts = ax.boxplot([df.loc[df["symbol"] == s, "bps"] for s in syms], patch_artist=True, widths=0.55)
        ax.set_xticks(range(1, len(syms) + 1), syms)
        for patch, s in zip(parts["boxes"], syms):
            patch.set_facecolor(COLORS.get(s)); patch.set_alpha(0.55)
        ax.axhline(0, color="#9ca3af", linewidth=0.8, linestyle="--")
        ax.set_ylabel("One-minute return (basis points)")
        finish(fig, ax, "Distribution of one-minute returns by stock", "03-return-distribution")

        # 4. Row counts per layer (the pipeline reconciles end to end)
        df = query(conn, """
            SELECT 'Bronze' AS layer, (SELECT COUNT(*) FROM MARKET_AGENT.BRONZE.RAW_BARS) AS bars,
                   (SELECT COUNT(*) FROM MARKET_AGENT.BRONZE.RAW_TRADES) AS trades
            UNION ALL SELECT 'Silver', (SELECT COUNT(*) FROM MARKET_AGENT.SILVER.BARS),
                   (SELECT COUNT(*) FROM MARKET_AGENT.SILVER.TRADES)
            UNION ALL SELECT 'Gold', (SELECT COUNT(*) FROM MARKET_AGENT.GOLD.FCT_BARS),
                   (SELECT COUNT(*) FROM MARKET_AGENT.GOLD.FCT_TRADES)""")
        fig, ax = plt.subplots(figsize=(10, 4.5))
        x = range(len(df))
        b1 = ax.bar([i - 0.2 for i in x], df["bars"], width=0.4, color="#60a5fa", label="Bars")
        b2 = ax.bar([i + 0.2 for i in x], df["trades"], width=0.4, color="#a78bfa", label="Trades")
        ax.bar_label(b1, fmt="{:,.0f}"); ax.bar_label(b2, fmt="{:,.0f}")
        ax.set_xticks(list(x), df["layer"])
        ax.set_ylabel("Rows")
        ax.legend(frameon=False)
        finish(fig, ax, "Rows per layer: Bronze → Silver → Gold reconcile exactly", "04-layer-reconciliation")


if __name__ == "__main__":
    main()
