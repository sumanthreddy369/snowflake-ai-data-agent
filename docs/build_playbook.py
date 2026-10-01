"""
Builds docs/snowflake-e2e-agent-playbook.pdf: the real-time problems data
engineers and analysts hit on this stack, the agent assigned to each one, and
how those agents are trained and tested before they're trusted.

The content lives in the data structures below (AGENTS, STAGES, TRAIN_ROWS,
E2E, SF_BUILD) rather than in a word-processor file, so the playbook can be
diffed and reviewed in git like the code it describes, and regenerated when
the plan changes. Problem counts and IDs are computed from STAGES, not typed
by hand.

Needs `reportlab` (pip install reportlab). Uses a Unicode TrueType font so
arrows and typographic quotes render; the built-in PDF fonts can't draw them.
"""

import argparse
import logging
from pathlib import Path

from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("build_playbook")

# Resolved from this file's location, not the caller's working directory.
DEFAULT_OUT = Path(__file__).resolve().parent / "snowflake-e2e-agent-playbook.pdf"

# (regular, bold, italic) candidates in preference order: Windows Arial, then
# DejaVu Sans (most Linux distros), then Arial on macOS.
FONT_CANDIDATES = [
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/ariali.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"),
    ("/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf", "/Library/Fonts/Arial Italic.ttf"),
]


def register_fonts() -> None:
    for regular, bold, italic in FONT_CANDIDATES:
        if all(Path(f).exists() for f in (regular, bold, italic)):
            pdfmetrics.registerFont(TTFont("Body", regular))
            pdfmetrics.registerFont(TTFont("Body-Bold", bold))
            pdfmetrics.registerFont(TTFont("Body-Italic", italic))
            registerFontFamily("Body", normal="Body", bold="Body-Bold", italic="Body-Italic", boldItalic="Body-Bold")
            logger.info("using font %s", regular)
            return
    raise SystemExit("No Unicode TrueType font found; add one to FONT_CANDIDATES.")


INK = colors.HexColor("#1F2937")
MUTED = colors.HexColor("#6B7280")
ACCENT = colors.HexColor("#1D4ED8")
RULE = colors.HexColor("#D1D5DB")
HEAD_BG = colors.HexColor("#1E3A8A")
ZEBRA = colors.HexColor("#F3F4F6")
NOTE_BG = colors.HexColor("#EFF6FF")

S = {
    "title": ParagraphStyle("title", fontName="Body-Bold", fontSize=24, leading=29, textColor=INK, spaceAfter=6),
    "subtitle": ParagraphStyle("subtitle", fontName="Body", fontSize=12, leading=16, textColor=MUTED, spaceAfter=14),
    "h1": ParagraphStyle("h1", fontName="Body-Bold", fontSize=16, leading=20, textColor=HEAD_BG, spaceBefore=10, spaceAfter=6),
    "h2": ParagraphStyle("h2", fontName="Body-Bold", fontSize=12, leading=15, textColor=INK, spaceBefore=8, spaceAfter=4),
    "body": ParagraphStyle("body", fontName="Body", fontSize=9.5, leading=13.5, textColor=INK, spaceAfter=5),
    "bullet": ParagraphStyle("bullet", fontName="Body", fontSize=9.5, leading=13.5, textColor=INK,
                             leftIndent=12, bulletIndent=2, spaceAfter=2),
    "cell": ParagraphStyle("cell", fontName="Body", fontSize=7.8, leading=10, textColor=INK, alignment=TA_LEFT),
    "cellb": ParagraphStyle("cellb", fontName="Body-Bold", fontSize=7.8, leading=10, textColor=INK),
    "cellh": ParagraphStyle("cellh", fontName="Body-Bold", fontSize=8, leading=10, textColor=colors.white),
    "note": ParagraphStyle("note", fontName="Body", fontSize=9, leading=12.5, textColor=INK),
}


def P(text, style="body"):
    return Paragraph(text, S[style])


def bullets(items):
    return [Paragraph(t, S["bullet"], bulletText="•") for t in items]


def note(text):
    t = Table([[P(text, "note")]], colWidths=[7.5 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NOTE_BG),
        ("LINEBEFORE", (0, 0), (0, -1), 3, ACCENT),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return t


def grid(header, rows, widths, bold_first=True):
    data = [[P(h, "cellh") for h in header]]
    for r in rows:
        data.append([P(c, "cellb" if (i == 0 and bold_first) else "cell") for i, c in enumerate(r)])
    t = Table(data, colWidths=[w * inch for w in widths], repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))
    t.setStyle(TableStyle(style))
    return t


# ---------------------------------------------------------------- agents
AGENTS = [
    ("WATCH", "Ingestion Watchdog",
     "Alpaca feed, Kafka, Kafka Connect, Snowpipe Streaming, GCS/Snowpipe batch loads",
     "Alpaca /v2/clock + /v2/calendar; Kafka consumer-group lag and topic offsets (read-only admin API); "
     "Kafka Connect REST status; SNOWPIPE_STREAMING_CLIENT/CHANNEL history; SYSTEM$PIPE_STATUS; COPY_HISTORY; DLQ topic reader"),
    ("DOCTOR", "Pipeline Doctor",
     "Streams, Tasks, Dynamic Tables, dbt runs",
     "SHOW STREAMS (stale flag); TASK_HISTORY; DYNAMIC_TABLE_REFRESH_HISTORY; dbt run_results.json + manifest.json; "
     "EXECUTE TASK / RESUME TASK (approval-gated)"),
    ("DQ", "Data Quality Sentinel",
     "Correctness of the numbers in Bronze, Silver and Gold",
     "Row-count reconciliation queries across layers; FCT_BARS.is_suspect; ONNX anomaly model score; "
     "Alpaca corporate-actions API; sql/08_validation queries"),
    ("XFORM", "Transformation Copilot",
     "dbt models, schema changes, tests, docs",
     "Git repo (read + open PR only); dbt parse/compile/test against a dev schema; INFORMATION_SCHEMA.COLUMNS diff"),
    ("ANALYST", "Analyst Copilot",
     "Business questions from humans (this is the Cortex Agent the repo already defines)",
     "Cortex Analyst over MARKET_SEMANTIC_VIEW; Cortex Search over NEWS_SEARCH_SERVICE; freshness lookup on Gold"),
    ("CURATOR", "Semantic Curator",
     "Semantic model quality: metrics, synonyms, verified queries",
     "semantic_model.yaml + semantic_view.sql (read + PR); AGENT_QUERY_AUDIT_LOG; thumbs-down feedback table"),
    ("GUARD", "Governance and Cost Guard",
     "Access, licensing, policy drift, credit spend, prompt injection",
     "POLICY_REFERENCES; GRANTS_TO_ROLES; ACCESS_HISTORY; WAREHOUSE_METERING_HISTORY; CORTEX usage views; resource monitors"),
    ("SCALE", "Capacity and Resilience",
     "Load spikes, scaling, outages, failover and catch-up after recovery",
     "WAREHOUSE_LOAD_HISTORY; QUERY_HISTORY queued/blocked time; Kafka broker disk and throughput metrics; "
     "connector task counts; replication/failover group status; ALTER WAREHOUSE within fixed size limits (pre-approved)"),
    ("TRIAGE", "Incident Triage (orchestrator)",
     "Any alert; decides which specialist agent handles it",
     "Calls the other agents as tools; writes the incident timeline; pages a human with a summary"),
]

# --------------------------------------------------------------- problems
# (id, problem + symptom, who, agent + fix, guardrail)
STAGES = [
    ("A. Market-data source (Alpaca websocket + REST)", [
        ("A1", "<b>Silent stall.</b> Websocket stays connected but stops sending messages, so the pipeline looks healthy while prices freeze.",
         "DE", "<b>WATCH</b> compares last-message age against the Alpaca market clock: no messages for 60 s while the market is open is an incident. Restarts the producer through its runbook.",
         "Auto-restart allowed once; a second stall pages a human."),
        ("A2", "<b>“No data” vs “broken”.</b> Weekends, holidays, half-days and pre-market look identical to an outage. Alerts fire every Saturday.",
         "DE", "<b>WATCH</b> checks /v2/calendar before raising anything. Suppresses alerts outside trading sessions and says so in the alert text.",
         "Calendar cached daily; a mismatch with exchange calendar is flagged."),
        ("A3", "<b>Reconnect duplicates and gaps.</b> After a reconnect some trades repeat and some minutes are missing.",
         "DE", "<b>DQ</b> finds missing minute bars per symbol and duplicate trade_ids, then asks WATCH to backfill the exact window via REST.",
         "Backfill limited to the gap window; never rewrites outside it."),
        ("A4", "<b>Rate limits (HTTP 429) during backfill.</b> Large history pulls fail halfway.",
         "DE", "<b>WATCH</b> reads the failure, re-plans the backfill into smaller symbol/date chunks, resumes from the last successful chunk.",
         "Concurrency cap set in config, not chosen by the agent."),
        ("A5", "<b>Corporate actions.</b> A 4:1 split makes a stock look like it fell 75%. Ticker renames (FB to META) split history in two.",
         "DE + Analyst", "<b>DQ</b> joins suspect moves against the corporate-actions API. Labels split-driven moves as explained, proposes an adjustment-factor table.",
         "Price adjustment is a reviewed PR, never an in-place update."),
        ("A6", "<b>Trade corrections and cancels.</b> Exchanges cancel or correct prints; condition codes mark odd-lot or out-of-sequence trades.",
         "DE + Analyst", "<b>XFORM</b> proposes a condition-code filter in stg_trades; <b>DQ</b> reports how many trades each rule removes.",
         "Filter rules documented and tested in dbt."),
        ("A7", "<b>Feed coverage mismatch.</b> Free Alpaca IEX feed is a small share of total volume. Analysts compare to Bloomberg and think the data is wrong.",
         "Analyst", "<b>ANALYST</b> states the feed source in every volume answer and explains the gap when a user disputes a number.",
         "Feed name stored as a column, not assumed."),
        ("A8", "<b>Vendor schema drift.</b> A new field appears or a type changes, and validation starts rejecting every message.",
         "DE", "<b>WATCH</b> sees the DLQ rate spike, clusters DLQ errors by field, and hands a summary to <b>XFORM</b> to draft a schema update.",
         "Schema change goes through PR + CI; DLQ is replayed after merge."),
        ("A9", "<b>Timezone and DST bugs.</b> ET vs UTC confusion shifts the trading day; the DST weekend breaks “today”.",
         "DE + Analyst", "<b>DQ</b> asserts that every session has 390 minute bars between 13:30/14:30 UTC and 20:00/21:00 UTC depending on DST.",
         "Assertion lives in dbt tests, not only in the agent."),
    ]),
    ("B. Kafka and Kafka Connect", [
        ("B1", "<b>Consumer lag growing.</b> Connector falls behind; “real-time” data becomes minutes old.",
         "DE", "<b>WATCH</b> tracks lag trend, not a single value. Diagnoses cause (connector down, hot partition, slow Snowflake) and recommends a fix.",
         "Scaling tasks or partitions needs approval."),
        ("B2", "<b>DLQ grows silently.</b> Bad messages are routed correctly, then nobody ever looks at them.",
         "DE", "<b>WATCH</b> summarises the DLQ daily: top error types, affected symbols, whether the rows are replayable.",
         "Replay of DLQ only after the root cause is fixed."),
        ("B3", "<b>Hot partitions.</b> TSLA/NVDA traffic lands on one partition and lags while others idle.",
         "DE", "<b>WATCH</b> reports per-partition lag and proposes a different keying strategy.",
         "Repartitioning is a planned change, never automatic."),
        ("B4", "<b>Retention expires before catch-up.</b> A long outage means Kafka deletes data that never reached Snowflake.",
         "DE", "<b>WATCH</b> projects time-to-retention-expiry from current lag and escalates early; <b>TRIAGE</b> triggers REST backfill for the lost window.",
         "Escalation threshold set as a fixed fraction of retention."),
        ("B5", "<b>Connector task failures.</b> A task dies with a stack trace; restarts loop.",
         "DE", "<b>WATCH</b> reads the Connect REST trace, matches it to known causes (auth, channel invalidated, schema), applies the runbook step.",
         "One automated restart; repeat failure goes to a human."),
    ]),
    ("C. Loading into Snowflake (Snowpipe Streaming, Snowpipe, GCS)", [
        ("C1", "<b>Duplicates after a connector restart.</b> Offset tokens reset or channels are reopened, so rows load twice.",
         "DE", "<b>DQ</b> checks Bronze duplicate rate per channel after every restart event and reports it; Silver MERGE dedupes by key.",
         "Silver keeps the dedupe; the agent only reports."),
        ("C2", "<b>Batch loads fail silently.</b> GCS file lands, COPY rejects rows, nobody notices. Or the Pub/Sub notification integration is misconfigured and nothing loads.",
         "DE", "<b>WATCH</b> compares files in the bucket with COPY_HISTORY and SYSTEM$PIPE_STATUS; reports files never loaded or partially loaded.",
         "Reload uses a named file list, never a full re-scan."),
        ("C3", "<b>Load-history dedupe.</b> Re-uploading a fixed file with the same name is skipped by Snowpipe.",
         "DE", "<b>WATCH</b> recognises the “already loaded” case and proposes the correct reload path.",
         "FORCE reloads require approval (risk of duplicates)."),
        ("C4", "<b>Backfill overlaps streaming.</b> The boundary minute exists in both paths.",
         "DE", "<b>DQ</b> checks the overlap window after each backfill and confirms the MERGE kept one row per key.",
         "Overlap window defined explicitly per backfill run."),
        ("C5", "<b>Small-file cost.</b> Thousands of tiny files raise Snowpipe overhead.",
         "DE", "<b>GUARD</b> reports cost per loaded GB and suggests batching thresholds.",
         "Recommendation only."),
    ]),
    ("D. Bronze to Silver (Streams + Tasks, Dynamic Tables)", [
        ("D1", "<b>Stale stream.</b> A stream not consumed within the retention window becomes stale; the only fix is recreate, and changes in between are lost.",
         "DE", "<b>DOCTOR</b> watches stream staleness dates and warns days ahead; if stale, runs the recreate + gap-backfill runbook.",
         "Recreate needs approval; the gap backfill is logged."),
        ("D2", "<b>Suspended or failing tasks.</b> A task fails repeatedly and auto-suspends; Silver stops updating.",
         "DE", "<b>DOCTOR</b> reads TASK_HISTORY errors, classifies (SQL error, warehouse, permissions), fixes known causes, resumes.",
         "RESUME TASK allowed only for classified known causes."),
        ("D3", "<b>Non-deterministic MERGE.</b> Duplicate keys in the source batch make MERGE fail.",
         "DE", "<b>DOCTOR</b> identifies the duplicate keys, explains which path produced them (see C1/C4).",
         "Fix goes into the QUALIFY dedupe, via PR."),
        ("D4", "<b>Silent nulls from TRY_TO_ casts.</b> Bad values become NULL instead of failing; data quietly disappears from metrics.",
         "DE + Analyst", "<b>DQ</b> tracks the NULL rate per cast column per hour and alerts on jumps.",
         "Threshold reviewed by a human once, then fixed in config."),
        ("D5", "<b>Dynamic Table lag misses.</b> Refreshes fall behind TARGET_LAG or fail.",
         "DE", "<b>DOCTOR</b> reads DYNAMIC_TABLE_REFRESH_HISTORY and explains why (upstream, warehouse size, query change).",
         "Warehouse resizing needs approval."),
    ]),
    ("E. Silver to Gold (dbt)", [
        ("E1", "<b>Full rebuilds get slow and expensive.</b> Table materialisation rebuilds all history every run.",
         "DE", "<b>XFORM</b> drafts incremental versions with a late-arrival lookback window and compares outputs against the full rebuild.",
         "Merge only if row-by-row diff is zero on a test window."),
        ("E2", "<b>2 a.m. test failure.</b> dbt test fails; the on-call engineer has to work out which test, which rows, and whether it is real.",
         "DE", "<b>DOCTOR</b> reads run_results.json, runs the failing test's SQL, returns failing rows and the likely cause.",
         "The agent never disables or weakens a test."),
        ("E3", "<b>Upstream schema change breaks models.</b>",
         "DE", "<b>XFORM</b> diffs INFORMATION_SCHEMA before/after, finds affected models via the dbt DAG, opens a fix PR.",
         "CI must pass; human review required."),
        ("E4", "<b>Grants and policies lost on rebuild.</b> CREATE OR REPLACE drops row access policies and table grants (found and fixed in this repo in commit a480e77).",
         "DE", "<b>GUARD</b> runs the POLICY_REFERENCES check after every dbt run; missing policy is a sev-1.",
         "Sev-1 pauses agent answers until fixed."),
        ("E5", "<b>Window metrics wrong at boundaries.</b> Rolling volatility runs across the overnight gap or across a split.",
         "Analyst", "<b>DQ</b> tests that rolling windows reset per session; <b>XFORM</b> proposes partitioning by trading date.",
         "Metric definition change requires CURATOR update too."),
        ("E6", "<b>Docs drift.</b> README run order no longer matches the code (also found in this repo).",
         "DE", "<b>XFORM</b> checks documented commands and object names against the code on every PR.",
         "Flags only; a human edits the docs."),
    ]),
    ("F. Semantic layer, Cortex Analyst, Cortex Agent (analyst-facing)", [
        ("F1", "<b>Ambiguous questions.</b> “What's AAPL's return today?” before the open, or “return” meaning close-to-close vs open-to-close.",
         "Analyst", "<b>ANALYST</b> asks one clarifying question or states the assumption it used (definition, timezone, session).",
         "Definitions come from the semantic model, not the model's guess."),
        ("F2", "<b>Wrong SQL that looks right.</b> Bad join, wrong grain, wrong filter: a confident wrong number.",
         "Analyst", "<b>ANALYST</b> shows the SQL it ran; <b>CURATOR</b> regression-tests every verified query nightly against sql/08_validation twins.",
         "Answers without a verified pattern are labelled as such."),
        ("F3", "<b>Two sources of truth.</b> semantic_model.yaml and semantic_view.sql define metrics separately and drift apart.",
         "DE + Analyst", "<b>CURATOR</b> diffs the two definitions on every PR and fails CI on mismatch.",
         "Single owner signs off on metric changes."),
        ("F4", "<b>Routing errors.</b> Agent sends a “why did it move” question to SQL only, or a numeric question to search.",
         "Analyst", "<b>CURATOR</b> keeps a labelled set of routing examples and scores the agent on it after each instruction change.",
         "Routing accuracy target agreed before rollout."),
        ("F5", "<b>RAG problems.</b> News index lags (TARGET_LAG 1 h), wrong-ticker articles (“F” is Ford; “Apple” in a recipe), missing citations.",
         "Analyst", "<b>ANALYST</b> filters search by symbol attribute, always cites, and states article timestamps. <b>DQ</b> measures retrieval precision on a labelled set.",
         "No citation means no news claim in the answer."),
        ("F6", "<b>“The data is wrong” that is actually the 15-minute delay.</b> Delayed-entitlement users see older prices than a live screen.",
         "Analyst", "<b>ANALYST</b> states the as-of timestamp and entitlement in every price answer.",
         "Policy enforced in Snowflake; the agent only explains it."),
        ("F7", "<b>Suspect bars in aggregates.</b> One bad print distorts daily return or volatility.",
         "Analyst", "<b>ANALYST</b> checks is_suspect rows in scope and mentions them; offers the figure with and without them.",
         "Suspect rows are flagged, never silently dropped."),
        ("F8", "<b>Waiting on engineering for every new metric.</b>",
         "Analyst", "<b>CURATOR</b> mines unanswered questions from the audit log and drafts new metrics + verified queries as a PR.",
         "Data engineer reviews every new metric."),
        ("F9", "<b>Slow or expensive answers.</b> Agent calls time out or cost too much per question.",
         "Analyst + DE", "<b>GUARD</b> tracks latency and credits per question type; <b>CURATOR</b> adds pre-aggregated views for the heaviest patterns.",
         "Per-role statement timeout already in sql/09_guardrails."),
    ]),
    ("G. Governance, security and cost", [
        ("G1", "<b>Licence leakage.</b> A role that shouldn't see real-time prices gets them through a new grant or a new table.",
         "DE", "<b>GUARD</b> diffs grants daily and checks every new Gold table for the row access policy.",
         "New grants to REALTIME_DESK always need human approval."),
        ("G2", "<b>Prompt injection through news.</b> A news article contains text like “ignore your instructions and…”, and the agent reads it as a command.",
         "DE", "<b>GUARD</b> screens retrieved text and the agent treats search results as data only; the agent's role has read-only grants, so even a successful injection cannot change data.",
         "Least-privilege role is the real defence, not the screen."),
        ("G3", "<b>Runaway spend.</b> A loop of agent queries or a bad dbt model burns credits overnight.",
         "DE", "<b>GUARD</b> watches metering per warehouse and per role and suspends at the resource-monitor threshold.",
         "Resource monitor in sql/09_guardrails is the hard stop."),
        ("G4", "<b>Audit gaps.</b> Can't prove who asked what and what data they saw.",
         "DE", "<b>GUARD</b> reconciles AGENT_QUERY_AUDIT_LOG with QUERY_HISTORY and reports missing entries.",
         "Audit table is append-only."),
        ("G5", "<b>Secret rotation.</b> Alpaca keys and Snowflake key pairs expire or leak.",
         "DE", "<b>GUARD</b> tracks key age and reminds before expiry.",
         "Agents never read or store secret values."),
    ]),
    ("I. Data volume and overload", [
        ("I1", "<b>Market-open and close spikes.</b> Volume at 9:30 and 16:00 ET is many times the midday rate; producer, Kafka and Snowpipe Streaming all lag at once.",
         "DE", "<b>SCALE</b> pre-scales connector tasks and warehouses before the open using the market calendar, then scales back after the spike.",
         "Schedule pre-approved; hard size cap."),
        ("I2", "<b>Event-day surges.</b> CPI, FOMC, earnings or a meme-stock day brings sudden, unplanned volume far above normal.",
         "DE", "<b>SCALE</b> compares throughput with the same time-of-day baseline, scales within limits, and warns <b>DQ</b> to expect late data.",
         "Resource-monitor credit ceiling still applies."),
        ("I3", "<b>Producer backpressure.</b> The producer's send buffer fills; it either drops messages or runs out of memory.",
         "DE", "<b>WATCH</b> tracks buffer use and send errors and alerts before the buffer is full.",
         "Producer configured to block, never silently drop."),
        ("I4", "<b>Kafka broker disk full.</b> A surge plus long retention fills disks; brokers stop accepting writes.",
         "DE", "<b>SCALE</b> projects time-to-full from the fill rate and proposes retention or disk changes early.",
         "Retention/disk changes need approval."),
        ("I5", "<b>Snowpipe Streaming throttling.</b> Client hits throughput or channel limits and starts returning errors.",
         "DE", "<b>WATCH</b> reads client errors; <b>SCALE</b> proposes more channels or connector tasks.",
         "Changes go through config review."),
        ("I6", "<b>Warehouse queuing.</b> Tasks, dbt and agent queries compete for compute; queries queue and Silver falls behind at peak.",
         "DE", "<b>SCALE</b> reads queued time in QUERY_HISTORY and proposes separate or multi-cluster warehouses (ANALYST_WH is already separate).",
         "Bigger warehouses need approval."),
        ("I7", "<b>Many analysts at once.</b> Morning question bursts hit Cortex and the warehouse together; answers time out.",
         "Analyst", "<b>GUARD</b> rate-limits per user; <b>SCALE</b> enables multi-cluster scaling for ANALYST_WH within limits.",
         "Per-role statement timeout stays on."),
        ("I8", "<b>Huge scans.</b> A broad question makes the agent scan years of trades.",
         "Analyst + DE", "<b>ANALYST</b> adds a default date range and says so; <b>SCALE</b> suggests clustering keys for the common filters.",
         "Statement timeout is the hard stop."),
        ("I9", "<b>Storage growth from churn.</b> MERGE every minute multiplies Time Travel and Fail-safe storage.",
         "DE", "<b>GUARD</b> reports storage per table including Time Travel bytes and proposes transient Bronze or shorter retention.",
         "Retention changes need approval."),
    ]),
    ("J. Outages and recovery (server down)", [
        ("J1", "<b>Alpaca outage or degraded feed.</b> Vendor is down or sending partial data during market hours.",
         "DE + Analyst", "<b>WATCH</b> detects it, records the window in an OPS outage table; <b>ANALYST</b> tells users that window is incomplete; backfill runs when the vendor recovers.",
         "Outage windows are recorded, never hidden."),
        ("J2", "<b>Kafka broker down or quorum lost.</b> Producer can't write.",
         "DE", "<b>WATCH</b> detects write failures; <b>TRIAGE</b> pages with the broker state and the data at risk.",
         "Agents never restart cluster nodes on their own."),
        ("J3", "<b>Kafka Connect worker crash or rebalance storm.</b> Tasks keep moving between workers and nothing loads.",
         "DE", "<b>WATCH</b> spots repeated rebalances in the Connect logs and recommends the runbook fix.",
         "One automated restart, then a human."),
        ("J4", "<b>Snowflake unavailable</b> (region incident, or a warehouse can't resume).",
         "DE", "<b>TRIAGE</b> confirms with a probe query and the status page, and works out how long Kafka retention can buffer (see B4). Failover to a second region only if replication is set up.",
         "Failover is always a human decision."),
        ("J5", "<b>Cortex unavailable or model not available in the region.</b> Agent questions fail.",
         "Analyst", "<b>ANALYST</b> falls back to verified-query results or the direct Cortex Analyst path and says it is in degraded mode.",
         "No made-up answers in degraded mode."),
        ("J6", "<b>GCS or Pub/Sub notification outage.</b> Files land but no notification arrives, so nothing loads.",
         "DE", "<b>WATCH</b> compares the bucket listing with COPY_HISTORY and proposes ALTER PIPE ... REFRESH for the missed window.",
         "Refresh scoped to the window; approval needed."),
        ("J7", "<b>Recovery storm.</b> After an outage everything catches up at once and causes a second overload.",
         "DE", "<b>SCALE</b> paces the catch-up; <b>DQ</b> confirms completeness for the outage window afterwards.",
         "Catch-up plan logged with the incident."),
        ("J8", "<b>Partial outage.</b> Only some symbols or one partition stop; the global “last message” metric still looks fine.",
         "DE", "<b>DQ</b> checks freshness per symbol, not just overall.",
         "Per-symbol thresholds account for illiquid names."),
        ("J9", "<b>Bad deploy takes the pipeline down.</b> A SQL or dbt change breaks tasks or corrupts a table.",
         "DE", "<b>DOCTOR</b> links the failure to the change (git history + QUERY_HISTORY) and proposes a rollback or a Time Travel restore (AT/BEFORE, UNDROP).",
         "Restores need approval."),
    ]),
    ("K. Time and timestamp matching", [
        ("K1", "<b>Event time vs load time.</b> trade_ts (when it happened) and _loaded_at (when it arrived) get mixed up; metrics use the wrong one.",
         "DE + Analyst", "<b>DQ</b> tracks the lateness distribution (load minus event time); <b>XFORM</b> checks every model aggregates on event time.",
         "Event-time rule written in AGENTS.md."),
        ("K2", "<b>Producer clock skew.</b> A host without NTP stamps wrong times; latency comes out negative or impossible.",
         "DE", "<b>WATCH</b> flags negative or implausible latencies and names the host.",
         "Fix is NTP on the host, not adjusting data."),
        ("K3", "<b>Bar timestamp convention.</b> Alpaca stamps a minute bar at the start of the minute; other sources use the end. Joins are off by one minute.",
         "DE + Analyst", "<b>DQ</b> asserts the convention on each source; <b>CURATOR</b> documents it in the semantic model.",
         "Convention converted at Silver, once."),
        ("K4", "<b>Trades don't match bars.</b> Bars rebuilt from trades differ from vendor bars (feed coverage, condition filters, boundary inclusive/exclusive).",
         "DE + Analyst", "<b>DQ</b> reconciles rebuilt vs vendor bars within a tolerance and explains each difference type.",
         "Tolerances agreed with analysts."),
        ("K5", "<b>Late data after aggregates are built.</b> A bar is final, then a correction arrives.",
         "DE", "<b>DQ</b> measures how late data really arrives so the incremental lookback window (E1) is sized from evidence.",
         "Lookback set in config, reviewed."),
        ("K6", "<b>Out-of-order arrival.</b> Messages from different partitions arrive out of sequence; logic that assumes arrival order breaks.",
         "DE", "<b>XFORM</b> checks every window function orders by event time with a tie-breaker (trade_id).",
         "Enforced by a dbt test."),
        ("K7", "<b>Precision truncation.</b> Nanosecond timestamps cut to milliseconds or seconds create duplicate (symbol, ts) keys and MERGE collisions.",
         "DE", "<b>DQ</b> checks key uniqueness and timestamp precision per column.",
         "Columns declared TIMESTAMP_NTZ(9)."),
        ("K8", "<b>Session timezone vs NTZ.</b> CURRENT_TIMESTAMP() is TIMESTAMP_LTZ; comparing it with a UTC NTZ column depends on the session TIMEZONE. With Snowflake's default America/Los_Angeles, a 15-minute delay rule can hide hours of data. <i>This repo's DELAYED_DATA_POLICY uses that comparison.</i>",
         "DE + Analyst", "<b>GUARD</b> tests the policy under several session timezones and fails if the visible window changes.",
         "Fix: compare against a UTC NTZ value (e.g. SYSDATE()); verify on live Snowflake."),
        ("K9", "<b>News-to-price alignment.</b> Using updated_at instead of published_at, or the wrong window, pins the wrong article to a price move.",
         "Analyst", "<b>ANALYST</b> searches only news published shortly before the move and states the time gap.",
         "No causal claim without a timestamp."),
        ("K10", "<b>Trading-day boundary.</b> date_key is the UTC day, so after-hours bars past 8 p.m. ET fall on the next day.",
         "Analyst", "<b>DQ</b> flags bars whose UTC date differs from the exchange date; <b>XFORM</b> proposes an exchange-time date_key.",
         "Metric change also updates CURATOR."),
    ]),
    ("L. Market structure and data correctness", [
        ("L1", "<b>Trading halts and LULD pauses.</b> No trades for minutes looks exactly like an outage.",
         "DE + Analyst", "<b>DQ</b> checks halt news before raising a gap; <b>WATCH</b> suppresses the outage alert for that symbol.",
         "Halt windows stored with source."),
        ("L2", "<b>Listings, delistings, symbol changes.</b> dim_symbols goes stale; the agent says “no data” for a valid ticker.",
         "DE + Analyst", "<b>DQ</b> diffs the symbol master daily and reports adds, removals and renames.",
         "History kept for inactive symbols."),
        ("L3", "<b>Bad prints the 10% rule misses.</b> Outliers within 10%, or legitimate moves above it.",
         "DE + Analyst", "<b>DQ</b> scores bars with the ONNX anomaly model alongside is_suspect and reports disagreements.",
         "Flag only; never delete."),
        ("L4", "<b>Illiquid gaps.</b> Thin symbols have minutes with no trades; teams disagree on forward-fill.",
         "Analyst", "<b>CURATOR</b> documents one gap rule; <b>XFORM</b> implements it consistently.",
         "Rule visible in metric descriptions."),
        ("L5", "<b>Extended hours mixed with the regular session.</b> Pre- and after-hours distort volume and returns.",
         "Analyst", "<b>ANALYST</b> defaults to the regular session and says so; session is a semantic-model dimension.",
         "Default stated in every answer."),
        ("L6", "<b>Unit mismatch.</b> A new source reports cents or lots instead of dollars or shares.",
         "DE", "<b>DQ</b> range-checks price and size per symbol against history.",
         "New sources start in quarantine."),
    ]),
    ("M. Concurrency, reprocessing and change", [
        ("M1", "<b>Task overlap.</b> A MERGE takes longer than its schedule; runs are skipped and lag builds.",
         "DE", "<b>DOCTOR</b> compares task duration with the schedule and recommends a new interval or warehouse size.",
         "ALLOW_OVERLAPPING_EXECUTION stays false."),
        ("M2", "<b>Lock contention.</b> A backfill MERGE and the streaming MERGE hit the same table; lock waits and timeouts follow.",
         "DE", "<b>DOCTOR</b> finds blocked queries and schedules backfills outside streaming peaks.",
         "Backfill windows planned in advance."),
        ("M3", "<b>Reprocessing history.</b> A bug fix means rebuilding months of data without double counting.",
         "DE", "<b>DOCTOR</b> plans the rebuild in a zero-copy clone, compares results, then proposes a swap.",
         "Swap needs approval; old table kept via Time Travel."),
        ("M4", "<b>Real-time vs batch disagree.</b> The streaming path and the backfill give different numbers for the same day.",
         "DE + Analyst", "<b>DQ</b> reconciles them daily; after T+1 the batch path is the source of truth.",
         "Rule documented for analysts."),
        ("M5", "<b>Environment drift.</b> Dev and prod objects differ, so a change works in dev and fails in prod.",
         "DE", "<b>XFORM</b> diffs GET_DDL output between environments before deploys.",
         "Deploys blocked on drift."),
        ("M6", "<b>Bad data reaches Gold.</b> Wrong numbers are already published.",
         "DE + Analyst", "<b>DOCTOR</b> proposes a Time Travel restore; <b>ANALYST</b> flags answers given during the bad window (from the audit log).",
         "Restore needs approval; users told."),
    ]),
    ("N. Analyst trust and reproducibility", [
        ("N1", "<b>Same question, different answer.</b> Asked at 10:05 and 10:30, numbers differ because of late data and the delay window.",
         "Analyst", "<b>ANALYST</b> gives an as-of time with every answer; the audit log keeps the SQL so it can be re-run with Time Travel AT that time.",
         "Audit log is append-only."),
        ("N2", "<b>Look-ahead bias.</b> Backtests use corrected prints or news that weren't available at the time.",
         "Analyst", "<b>CURATOR</b> provides point-in-time views filtered on _loaded_at.",
         "Backtest questions use point-in-time views."),
        ("N3", "<b>Survivorship bias.</b> Delisted symbols missing from history inflate returns.",
         "Analyst", "<b>ANALYST</b> includes inactive symbols for historical questions and warns when the universe changed.",
         "dim_symbols keeps inactive rows."),
        ("N4", "<b>Metric disputes.</b> Teams calculate VWAP or return differently.",
         "Analyst", "<b>CURATOR</b> keeps one definition per metric, with synonyms that map to it.",
         "Metric owner signs off."),
        ("N5", "<b>Dashboard load.</b> BI tools refresh Gold every few seconds.",
         "DE", "<b>SCALE</b> routes BI to its own warehouse and relies on the result cache; <b>GUARD</b> reports top consumers.",
         "Recommendation only."),
        ("N6", "<b>Questions outside the data.</b> Fundamentals, options, other markets: the risk is a made-up answer.",
         "Analyst", "<b>ANALYST</b> says the data isn't available; <b>CURATOR</b> logs it as demand for new data.",
         "No answer without a source."),
    ]),
    ("O. Operations and people", [
        ("O1", "<b>Root cause spans six systems.</b> A stale Gold number could start in Alpaca, Kafka, Snowpipe, a task, dbt or the agent.",
         "DE", "<b>TRIAGE</b> walks the chain upstream, asking each specialist agent for its health, and returns the first broken link with evidence.",
         "Summary goes to a human; actions stay with specialists."),
        ("O2", "<b>Reconciliation across layers.</b> Kafka offsets vs Bronze rows vs Silver vs Gold don't add up.",
         "DE", "<b>DQ</b> runs per-hour count reconciliation and reports the layer where rows disappear.",
         "Tolerances set per layer (dedupe expected in Silver)."),
        ("O3", "<b>Alert fatigue.</b> Dozens of alerts for one root cause.",
         "DE", "<b>TRIAGE</b> groups related alerts into one incident with a timeline.",
         "Raw alerts still logged."),
        ("O4", "<b>Tribal knowledge and missing runbooks.</b> Only one person knows how to fix a stale stream.",
         "DE", "Every agent fix is written as a runbook step first; <b>TRIAGE</b> writes a post-incident note proposing a new runbook entry.",
         "Runbooks reviewed and versioned in git."),
        ("O5", "<b>No CI, no tests (this repo's current gap).</b> Changes reach Snowflake untested.",
         "DE", "<b>XFORM</b> runs dbt parse/test and Python tests on every PR once CI exists.",
         "Build pytest + CI first (README Target items)."),
    ]),
]

# ---------------------------------------------------------- training plan
TRAIN_ROWS = [
    ("WATCH", "Runbooks for each stage of ingestion; market calendar rules; Kafka/Connect error catalogue.",
     "Fault injection with replay_sample_data.py: kill producer, drop minutes, duplicate bursts, malformed rows, pause connector.",
     "Detects fault within N minutes; correct root cause; correct runbook step; zero alerts on closed-market periods."),
    ("DOCTOR", "Task/stream/dbt failure catalogue with fixes; dbt DAG.",
     "Break things on a dev account: let a stream go stale, suspend a task, insert duplicate keys, fail a dbt test.",
     "Correct classification; failing rows returned; never weakens a test."),
    ("DQ", "Expected shapes: 390 bars per session, price bands, null-rate baselines, corporate-action rules.",
     "Inject splits, bad prints, gaps, halts, timezone shifts, clock skew, ms truncation, late and out-of-order rows into generated sample data.",
     "Precision/recall on injected faults; explained vs unexplained moves."),
    ("XFORM", "AGENTS.md conventions; dbt style; schema contracts.",
     "Historical schema changes replayed as tasks; known bugs (e.g. GOLD_GOLD, lost policy) as test cases.",
     "PR passes CI; reviewer accepts without major changes."),
    ("ANALYST", "Semantic model, metric definitions, delay/entitlement rules, citation rules.",
     "Question bank: verified queries, ambiguous questions, adversarial questions, news questions.",
     "Numeric answers match sql/08 twins; routing accuracy; citation present; correct clarification rate."),
    ("CURATOR", "Both semantic definitions; audit log; feedback table.",
     "Seed failed/unanswered questions; seed YAML vs semantic-view mismatches.",
     "Mismatch detection rate; accepted metric PRs."),
    ("GUARD", "Policy model (who sees real-time); cost budgets; injection patterns.",
     "Add a grant, create an unprotected table, plant injection text in sample_news.csv, run a cost spike, query the policy under different session timezones.",
     "Every planted violation detected; no false sev-1."),
    ("SCALE", "Time-of-day volume baselines; macro-event calendar; capacity limits of each component.",
     "replay_sample_data.py at 10x-50x --speedup; stop the Kafka container; suspend a warehouse; fill a test broker's disk.",
     "Lag recovers within the agreed time; no credit overrun; no data lost; catch-up paced."),
    ("TRIAGE", "Dependency graph of the stack; escalation policy.",
     "Composite incidents built from the scenarios above.",
     "First broken link identified; one incident per root cause."),
]


# ------------------------------------------------- Snowflake end to end
E2E = [
    ("1. Source", "Outside Snowflake: Alpaca websocket + REST; Kafka topics market-trades, market-bars, market-data-dlq",
     "A1–A9, B1–B5, I1–I4, J1–J3, K2, L1", "WATCH, SCALE",
     "Kafka lag + Connect status and Alpaca clock (external); results written into a Snowflake OPS table"),
    ("2. Ingest", "Snowpipe Streaming channels (Kafka connector); GCS storage integration, RAW_STAGE, BARS_BACKFILL_PIPE, SYMBOLS_PIPE, NEWS_PIPE",
     "C1–C5, I5, J4, J6, J7, K7", "WATCH, DQ, SCALE",
     "SNOWPIPE_STREAMING_* history, COPY_HISTORY, SYSTEM$PIPE_STATUS"),
    ("3. Bronze", "BRONZE.RAW_TRADES, RAW_BARS, RAW_SYMBOLS, RAW_NEWS (permissive VARCHAR)",
     "A3, A8, C1, D4, J8, K1, L2", "DQ",
     "Data Metric Functions: ROW_COUNT, DUPLICATE_COUNT, FRESHNESS"),
    ("4. Silver", "Streams RAW_*_STREAM + Tasks MERGE_*_TASK → SILVER.TRADES, BARS, SYMBOLS, NEWS; SYMBOLS_DT",
     "D1–D5, I6, K5, K6, M1, M2", "DOCTOR, SCALE",
     "SHOW STREAMS (stale_after), TASK_HISTORY, DYNAMIC_TABLE_REFRESH_HISTORY"),
    ("5. Gold", "dbt → STAGING views; GOLD.DIM_SYMBOLS, DIM_DATE, FCT_TRADES, FCT_BARS (is_suspect flag; row access policy via post-hook)",
     "E1–E6, A5, A6, A9, K3, K4, K10, L3–L6, M3–M6, J9", "DOCTOR, XFORM, DQ",
     "dbt run_results, POLICY_REFERENCES, NULL_COUNT DMFs, ONNX anomaly score"),
    ("6. Semantic + search", "GOLD.MARKET_SEMANTIC_VIEW; semantic_model.yaml; SILVER.NEWS_SEARCH_SERVICE (Cortex Search)",
     "F2–F5, F8, N2, N4", "CURATOR",
     "Verified-query regression against sql/08; search refresh lag"),
    ("7. Agent", "AGENTS.MARKET_DATA_AGENT (Cortex Agent with analyst + search tools), role ANALYST_AGENT",
     "F1–F9, I8, J5, K9, N1, N3, N6", "ANALYST",
     "GOVERNANCE.AGENT_QUERY_AUDIT_LOG, Cortex usage views"),
    ("8. Serve", "MCP server, Streamlit, FastAPI, all querying as ANALYST_AGENT through the same policy",
     "F6, F9, G2, I7, N5", "ANALYST, GUARD, SCALE",
     "Latency and error logs in an event table"),
    ("9. Govern + cost", "Roles, DELAYED_DATA_POLICY, ANALYST_WH, ANALYST_AGENT_MONITOR, audit log",
     "G1–G5, E4, I9, K8", "GUARD",
     "GRANTS_TO_ROLES, ACCESS_HISTORY, WAREHOUSE_METERING_HISTORY, resource monitors"),
]

SF_BUILD = [
    ("Triggers", "Snowflake ALERT objects (CREATE ALERT ... IF (EXISTS (query)) THEN ...) on a schedule; Data Metric Functions attached to Bronze, Silver and Gold tables",
     "Detects the condition inside Snowflake and wakes the right agent. No external scheduler is needed for in-Snowflake problems."),
    ("Agent brain", "Cortex Agents (the same mechanism as MARKET_DATA_AGENT), or an external agent calling Snowflake through the repo's MCP server",
     "ANALYST and CURATOR fit Cortex Agents naturally. WATCH has to reach Kafka and Alpaca, so it runs outside and writes its findings into Snowflake."),
    ("Tools", "Stored procedures, one per runbook step (for example RESUME_TASK_SAFE, RECREATE_STREAM_WITH_BACKFILL), owned by a dedicated OPS role",
     "The agent can only do what a procedure allows; the procedure checks preconditions and logs every call."),
    ("Approval", "An OPS.PENDING_ACTIONS table plus a Streamlit in Snowflake page where a human approves or rejects",
     "Implements L2 autonomy: the agent proposes, a human approves, the procedure runs."),
    ("Observability", "Event table (Snowflake Trail) for procedure and agent logs; ACCOUNT_USAGE and INFORMATION_SCHEMA views",
     "One place to reconstruct every incident and every agent decision."),
    ("Notification", "Notification integration (email, or a webhook to Slack)",
     "Alerts and approval requests reach humans without another system."),
    ("Evals", "OPS.EVAL_CASES and OPS.EVAL_RESULTS tables; scenarios replayed into a zero-copy CLONE of the database",
     "Fault scenarios run against a clone, so training runs never touch production."),
    ("Security", "A separate least-privilege role per agent (OPS_WATCH, OPS_DOCTOR, ...); ANALYST_AGENT stays read-only",
     "A wrong or compromised agent can only do what its role allows."),
]


def flow_diagram():
    W, H = 7.5 * inch, 2.15 * inch
    d = Drawing(W, H)
    rows = [
        [("Alpaca", "trades · bars · news"), ("Kafka", "+ DLQ topic"), ("Snowpipe", "Streaming + GCS batch"),
         ("Bronze", "RAW_* tables"), ("Silver", "Streams + Tasks")],
        [("Gold", "dbt star schema"), ("Semantic View", "+ Cortex Search"), ("Cortex Agent", "analyst | search"),
         ("Serve", "MCP · UI · API"), ("Governance", "policy · cost · audit")],
    ]
    agents = [["WATCH", "WATCH · SCALE", "WATCH · DQ", "DQ", "DOCTOR · SCALE"],
              ["XFORM · DQ", "CURATOR", "ANALYST", "ANALYST", "GUARD"]]
    bw, bh, gap = 1.28 * inch, 0.5 * inch, 0.275 * inch
    x0 = (W - (5 * bw + 4 * gap)) / 2
    ys = [H - 0.62 * inch, H - 1.72 * inch]
    for r, row in enumerate(rows):
        y = ys[r]
        for i, (name, sub) in enumerate(row):
            x = x0 + i * (bw + gap)
            outside = (r, i) in [(0, 0), (0, 1)]
            fill = colors.HexColor("#F3F4F6") if outside else colors.HexColor("#DBEAFE")
            d.add(Rect(x, y, bw, bh, rx=5, ry=5, fillColor=fill, strokeColor=ACCENT, strokeWidth=0.8))
            d.add(String(x + bw / 2, y + bh - 15, name, fontName="Body-Bold", fontSize=8.5, fillColor=INK, textAnchor="middle"))
            d.add(String(x + bw / 2, y + 8, sub, fontName="Body", fontSize=6.5, fillColor=MUTED, textAnchor="middle"))
            d.add(String(x + bw / 2, y - 10, agents[r][i], fontName="Body-Bold", fontSize=6.5, fillColor=ACCENT, textAnchor="middle"))
            if i < 4:
                ax = x + bw + 3
                d.add(Line(ax, y + bh / 2, ax + gap - 6, y + bh / 2, strokeColor=INK, strokeWidth=0.8))
                d.add(Polygon([ax + gap - 6, y + bh / 2 + 3, ax + gap - 2, y + bh / 2, ax + gap - 6, y + bh / 2 - 3],
                              fillColor=INK, strokeColor=INK))
    # Silver (end of row 1) wraps down to Gold (start of row 2)
    xs = x0 + 4 * (bw + gap) + bw / 2
    xg = x0 + bw / 2
    ymid = (ys[0] - 14 + ys[1] + bh) / 2
    d.add(Line(xs, ys[0] - 15, xs, ymid, strokeColor=INK, strokeWidth=0.8))
    d.add(Line(xs, ymid, xg, ymid, strokeColor=INK, strokeWidth=0.8))
    d.add(Line(xg, ymid, xg, ys[1] + bh + 4, strokeColor=INK, strokeWidth=0.8))
    d.add(Polygon([xg - 3, ys[1] + bh + 5, xg, ys[1] + bh + 1, xg + 3, ys[1] + bh + 5], fillColor=INK, strokeColor=INK))
    d.add(String(x0, 6, "Grey = outside Snowflake · Blue = inside Snowflake · Labels under boxes = agent watching that stage. TRIAGE and SCALE cover all of them.",
                 fontName="Body-Italic", fontSize=6.8, fillColor=MUTED))
    return d


def on_page(canvas, doc):
    canvas.saveState()
    canvas.setFont("Body", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(0.5 * inch, 0.4 * inch, "snowflake-ai-data-agent · Snowflake end-to-end agent playbook")
    canvas.drawRightString(8.0 * inch, 0.4 * inch, f"Page {doc.page}")
    canvas.restoreState()


def build(out: Path) -> None:
    doc = SimpleDocTemplate(str(out), pagesize=letter, leftMargin=0.5 * inch, rightMargin=0.5 * inch,
                            topMargin=0.55 * inch, bottomMargin=0.6 * inch,
                            title="Snowflake End-to-End Agent Playbook",
                            author="sumanthreddy369", subject="snowflake-ai-data-agent")
    st = []
    n_problems = sum(len(r) for _, r in STAGES)

    st += [P("Snowflake End-to-End: Real-Time Problems and Agent Playbook", "title"),
           P(f"snowflake-ai-data-agent · {n_problems} problems data engineers and analysts hit on this stack, "
             f"the agent that handles each one, and how to train those agents", "subtitle")]

    st.append(P("What this document is", "h1"))
    st.append(P(
        "The stack is Alpaca (trades, bars, news) → Kafka → Snowpipe Streaming and GCS batch loads → Bronze → "
        "Streams and Tasks → Silver → dbt → Gold → Semantic View and Cortex Search → Cortex Agent → MCP, Streamlit "
        "and FastAPI. Every stage has its own way of failing quietly. This playbook lists those failures as engineers "
        "and analysts actually meet them, assigns each one to an agent, and sets out how each agent is trained and "
        "tested before it is trusted."))
    st.append(note(
        "<b>Status:</b> none of these agents exist yet. The repo already has some foundations they would build on: "
        "DLQ routing, the is_suspect flag, the ONNX anomaly model, the Row Access Policy, the audit-log table and the "
        "sql/08 validation queries. Only the DLQ routing, sample data and ONNX training are verified; everything else "
        "has not run against live Snowflake. This is a plan, not a description of working software."))

    st.append(P("Who feels which problems", "h2"))
    st += bullets([
        "<b>Data engineers</b> own freshness, completeness, capacity and cost: feeds that stall, servers that go "
        "down, volume spikes that overload every component, timestamps that don't line up, tasks that suspend, "
        "tests that fail overnight, grants that disappear.",
        "<b>Analysts</b> own trust in the numbers: ambiguous definitions, confident wrong SQL, delayed data that looks "
        "broken, news citations that point to the wrong company, and waiting on engineering for every new metric.",
        "Many problems belong to both: a data engineer's silent NULL becomes an analyst's wrong average.",
    ])

    st.append(P("What “training” means for these agents", "h2"))
    st.append(P(
        "Most of these agents are LLM agents. They get better through what they are given and how they are tested, "
        "not by retraining model weights. Training each agent has five parts:"))
    st += bullets([
        "<b>Knowledge.</b> Runbooks, schemas, metric definitions and error catalogues, written down in the repo.",
        "<b>Tools.</b> A small set of narrow, mostly read-only tools (listed per agent below). Anything that changes "
        "state is approval-gated.",
        "<b>Scenarios.</b> Faults injected on purpose, using the repo's own sample-data generators and replay script, "
        "so every problem in this document becomes a repeatable test case with a known right answer.",
        "<b>Evals.</b> A scored test set per agent, run on every change to its instructions or tools. An agent is "
        "promoted only when it passes.",
        "<b>Feedback.</b> Every human correction in production becomes a new eval case, so the same mistake is caught "
        "next time.",
    ])
    st.append(P(
        "Real model training is used in only two places: the anomaly-detection model (the IsolationForest exported to "
        "ONNX, already in snowpark/) and, if evals plateau, fine-tuning for text-to-SQL or routing. Fine-tuning comes "
        "last, not first."))

    st.append(P("Autonomy levels", "h2"))
    st.append(grid(["Level", "What the agent may do", "Used for"], [
        ("L0 Observe", "Read metrics and logs, raise alerts.", "Every agent on day one."),
        ("L1 Diagnose", "Explain root cause with evidence; recommend a fix.", "Default level for most problems."),
        ("L2 Act with approval", "Run a runbook step after a human clicks approve.", "Restarts, backfills, resuming tasks."),
        ("L3 Act within bounds", "Run a pre-approved runbook step automatically, once, then escalate.",
         "Producer restart, alert suppression on closed markets."),
    ], [1.4, 3.6, 2.5]))

    st.append(PageBreak())
    st.append(P("Snowflake end to end", "h1"))
    st.append(P("The whole pipeline, from the market feed to the analyst's answer. Everything after Kafka runs inside "
                "Snowflake, so most problems can be detected, diagnosed and fixed with Snowflake's own objects and "
                "views. Problem IDs refer to the tables later in this document."))
    st.append(flow_diagram())
    st.append(Spacer(1, 6))
    st.append(grid(["Stage", "Snowflake objects in this repo", "Problems", "Agent", "Signal the agent reads"],
                   E2E, [0.95, 2.6, 0.85, 0.85, 2.25]))

    st.append(PageBreak())
    st.append(P("The agent roster", "h1"))
    st.append(P("Nine agents, each with one job. TRIAGE coordinates the others; ANALYST is the Cortex Agent "
                "the repo already defines in sql/10_agent."))
    st.append(grid(["Agent", "Owns", "Tools it is given"],
                   [(f"{code}<br/><font name='Body' size='7'>{name}</font>", owns, tools)
                    for code, name, owns, tools in AGENTS], [1.35, 2.25, 3.9]))

    st.append(PageBreak())
    st.append(P(f"The problems ({n_problems}), stage by stage", "h1"))
    st.append(P("Each row gives the problem as it shows up, who feels it, how the assigned agent handles it, and the "
                "guardrail or human step that keeps the agent safe."))
    for stage, rows in STAGES:
        st.append(P(stage, "h2"))
        st.append(grid(["#", "Problem and how it shows up", "Who", "How the agent solves it", "Guardrail"],
                       rows, [0.38, 2.35, 0.62, 2.65, 1.5]))
        st.append(Spacer(1, 4))

    st.append(PageBreak())
    st.append(P("How each agent is trained and tested", "h1"))
    st.append(P("Scenarios reuse what the repo already has: generate_sample_data.py and generate_sample_news.py "
                "produce clean data, a small fault-injection layer corrupts it in known ways, and "
                "replay_sample_data.py plays it through Kafka. Every scenario has an expected diagnosis, so it can be "
                "scored."))
    st.append(grid(["Agent", "Knowledge it is given", "Training scenarios", "Pass criteria (evals)"],
                   TRAIN_ROWS, [0.85, 2.0, 2.45, 2.2]))

    st.append(P("Feedback loop in production", "h2"))
    st += bullets([
        "Every agent action and answer is logged (AGENT_QUERY_AUDIT_LOG for ANALYST; an incident log for the others).",
        "Humans mark answers or actions as right or wrong; wrong ones become new eval cases with the corrected answer.",
        "The eval suite runs on every change to an agent's instructions, tools or the semantic model. A regression "
        "blocks the change.",
        "Agents move up an autonomy level only after a sustained pass rate on their evals and in production review.",
    ])

    st.append(PageBreak())
    st.append(P("Building the agents on Snowflake", "h1"))
    st.append(P("The agents don't need a separate platform. Each piece maps to a Snowflake feature, so detection, "
                "action, approval, logging and evaluation all sit next to the data they protect."))
    st.append(grid(["Piece", "Snowflake feature", "Why"], SF_BUILD, [1.0, 3.4, 3.1]))
    st.append(Spacer(1, 6))
    st.append(P("One problem end to end in Snowflake: a stale stream (D1)", "h2"))
    st += bullets([
        "<b>Detect.</b> A scheduled ALERT checks SHOW STREAMS output for any stream whose stale_after date is less "
        "than 2 days away.",
        "<b>Diagnose.</b> The alert calls DOCTOR, which reads TASK_HISTORY and finds the consuming task has been "
        "suspended since a failure 9 days ago.",
        "<b>Propose.</b> DOCTOR writes a row to OPS.PENDING_ACTIONS: fix the task error, resume it, and consume the "
        "stream before it goes stale. Evidence attached.",
        "<b>Approve.</b> The on-call engineer approves it on the Streamlit in Snowflake page.",
        "<b>Act.</b> The RESUME_TASK_SAFE procedure checks preconditions, resumes the task, and logs to the event table.",
        "<b>Verify.</b> DQ confirms Silver row counts have caught up with Bronze. The incident closes, and the case is "
        "added to OPS.EVAL_CASES so the next DOCTOR version is tested on it.",
    ])

    st.append(KeepTogether([
        P("Rollout order", "h1"),
        P("Built in the order that matches the repo's README plan, so each step has real infrastructure to test "
          "against:"),
        *bullets([
            "<b>Step 0: prerequisites.</b> Connect the live Snowflake trial, local Kafka, GCS bucket and Alpaca key; run "
            "every SQL file for real; build the pytest suite and CI (README “Target” items). Agents can't be evaluated "
            "against a pipeline that has never run.",
            "<b>Step 1: fault-injection harness.</b> Extend the sample generators so each problem in this document "
            "can be triggered on demand.",
            "<b>Step 2: L0/L1 observers.</b> WATCH, DQ, GUARD and SCALE (observe only) first, read-only. They catch the problems that "
            "silently damage data.",
            "<b>Step 3: analyst side.</b> ANALYST evals against the sql/08 twins, then CURATOR for the semantic model.",
            "<b>Step 4: repair agents.</b> DOCTOR, XFORM and SCALE actions (scaling, catch-up), approval-gated (L2).",
            "<b>Step 5: TRIAGE</b> once the specialists are reliable enough to call as tools.",
        ]),
    ]))

    doc.build(st, onFirstPage=on_page, onLaterPages=on_page)
    logger.info("wrote %s (%d problems, %d stages)", out, n_problems, len(STAGES))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    register_fonts()
    build(args.out)


if __name__ == "__main__":
    main()
