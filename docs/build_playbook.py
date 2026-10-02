"""
Builds docs/snowflake-e2e-agent-playbook.pdf: the real-time problems data
engineers and analysts hit on this stack, the agent assigned to each one, and
how those agents are trained and tested before they're trusted.

Problems, agents and training plans are read from
knowledge/problem_catalog.yaml -- the same file the agents load as
knowledge -- and validated against the Pydantic models below before anything
is rendered. Layout-only content (the end-to-end table, the Snowflake build
table, the narrative) stays in this script. Counts are computed, not typed.

Needs `reportlab` (pip install reportlab). Uses a Unicode TrueType font so
arrows and typographic quotes render; the built-in PDF fonts can't draw them.
"""

import argparse
import logging
import re
from pathlib import Path
from xml.sax.saxutils import escape

import yaml
from pydantic import BaseModel, Field, model_validator

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
DEFAULT_CATALOG = Path(__file__).resolve().parent.parent / "knowledge" / "problem_catalog.yaml"

# (regular, bold, italic) candidates in preference order: Windows Arial, then
# DejaVu Sans (most Linux distros), then Arial on macOS.
MONO_CANDIDATES = ["C:/Windows/Fonts/consola.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
                   "/System/Library/Fonts/Menlo.ttc"]

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
            mono = next((f for f in MONO_CANDIDATES if Path(f).exists()), None)
            if mono:
                pdfmetrics.registerFont(TTFont("Mono", mono))
            else:
                pdfmetrics.registerFont(TTFont("Mono", regular))
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
    "code": ParagraphStyle("code", fontName="Mono", fontSize=6.8, leading=8.4, textColor=INK),
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
        data.append([P(c, "cellb" if (i == 0 and bold_first) else "cell") if isinstance(c, str) else c
                     for i, c in enumerate(r)])
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


# --------------------------------------------------------------- catalog
# Problems, agents and training plans live in knowledge/problem_catalog.yaml,
# not here: the agents load that same file as knowledge, so the PDF and what
# the agents know can never drift apart. These models are the contract for it.


class Agent(BaseModel):
    code: str
    name: str
    owns: str
    tools: str


class Problem(BaseModel):
    id: str
    title: str
    symptom: str = ""
    who: str
    agents: list[str] = Field(min_length=1)
    solution: str
    guardrail: str
    bad_sql: str | None = None
    good_sql: str | None = None

    @model_validator(mode="after")
    def sql_pairs_come_together(self):
        if (self.bad_sql is None) != (self.good_sql is None):
            raise ValueError(f"{self.id}: bad_sql and good_sql must both be set or both be absent")
        return self


class Stage(BaseModel):
    id: str
    name: str
    problems: list[Problem] = Field(min_length=1)


class Training(BaseModel):
    agent: str
    knowledge: str
    scenarios: str
    pass_criteria: str


class Catalog(BaseModel):
    agents: list[Agent]
    stages: list[Stage]
    training: list[Training]

    @model_validator(mode="after")
    def references_are_consistent(self):
        # Cross-field checks belong here, not in a field_validator: they need
        # agents, stages and training all parsed first.
        codes = {a.code for a in self.agents}
        ids = [p.id for st in self.stages for p in st.problems]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate problem ids: {sorted(dupes)}")
        for st in self.stages:
            for prob in st.problems:
                unknown = set(prob.agents) - codes
                if unknown:
                    raise ValueError(f"{prob.id}: unknown agents {sorted(unknown)}")
                if not prob.id.startswith(st.id):
                    raise ValueError(f"{prob.id} is filed under stage {st.id}")
        missing = codes - {t.agent for t in self.training}
        if missing:
            raise ValueError(f"no training plan for agents {sorted(missing)}")
        return self


def load_catalog(path: Path) -> Catalog:
    return Catalog.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def rich(text: str, codes: set[str]) -> str:
    """Escape catalog text for reportlab and bold every agent code in it."""
    out = escape(text)
    return re.sub(r"\b(" + "|".join(sorted(codes, key=len, reverse=True)) + r")\b", r"<b>\1</b>", out)


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
     "G1–G5, E4, I9, K8, S1–S9, T1–T8", "GUARD",
     "GRANTS_TO_ROLES, ACCESS_HISTORY, WAREHOUSE_METERING_HISTORY, resource monitors"),
    ("10. SQL everywhere", "Every Silver MERGE, dbt model, verified query, analyst worksheet and agent-generated query",
     "P1–P14, Q1–Q11", "SQLCOACH",
     "EXPLAIN, GET_QUERY_OPERATOR_STATS, QUERY_HISTORY (spill, partitions scanned, rows produced)"),
    ("11. Develop → deploy", "Git, dbt CI, DEV/TEST/PROD databases (zero-copy clones), migration scripts",
     "R1–R12", "RELEASE",
     "CI results, GET_DDL diffs, OBJECT_DEPENDENCIES, ACCESS_HISTORY"),
    ("12. Analyst self-service", "Snowsight worksheets, BI tools, certified Gold objects, column comments",
     "U1–U9", "ANALYST, CURATOR",
     "ACCESS_HISTORY, QUERY_HISTORY by user, permission errors"),
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


def build(out: Path, cat: Catalog) -> None:
    codes = {a.code for a in cat.agents}
    doc = SimpleDocTemplate(str(out), pagesize=letter, leftMargin=0.5 * inch, rightMargin=0.5 * inch,
                            topMargin=0.55 * inch, bottomMargin=0.6 * inch,
                            title="Snowflake End-to-End Agent Playbook",
                            author="sumanthreddy369", subject="snowflake-ai-data-agent")
    st = []
    n_problems = sum(len(st.problems) for st in cat.stages)
    sql_problems = [p for st in cat.stages for p in st.problems if p.bad_sql]

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
        "<b>Approach:</b> the agent roles below are <i>responsibilities</i>, not a fleet of custom agents to build. "
        "Existing tools fill most of them (Snowflake alerts and Tasks, Dagster checks, dbt tests, Terraform, CI, and the "
        "Snowflake Cortex Agent); this project writes the glue between those tools and the guardrails around them, "
        "with the goal of removing repetitive human work while keeping human approval for anything that changes money, "
        "access or production (docs/production-readiness.md). <b>Status:</b> only the DLQ routing, sample data and ONNX "
        "training are verified; everything else is written but has not run against live Snowflake."))

    st.append(P("Who feels which problems", "h2"))
    st += bullets([
        "<b>Data engineers</b> own freshness, completeness, capacity and cost: feeds that stall, servers that go "
        "down, volume spikes that overload every component, timestamps that don't line up, tasks that suspend, "
        "tests that fail overnight, grants that disappear, deploys that break production, role sprawl and surprise bills.",
        "<b>Analysts</b> own trust in the numbers: ambiguous definitions, confident wrong SQL, slow queries, not finding the right table, delayed data that looks "
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

    st.append(P("How the agents understand these problems", "h2"))
    st.append(P(
        "Every problem in this document comes from one machine-readable file, knowledge/problem_catalog.yaml, "
        "which also holds the agent roster and training plans. The agents load it as knowledge: when they see a "
        "symptom they match it to a problem ID, follow that entry's solution, and stay inside its guardrail. The PDF "
        "is rendered from the same file, so what people read and what the agents know can't drift apart. Adding a "
        "problem means adding one entry; the build checks that every entry names a real agent and that every agent "
        "has a training plan."))

    st.append(KeepTogether([P("Autonomy levels", "h2"), grid(["Level", "What the agent may do", "Used for"], [
        ("L0 Observe", "Read metrics and logs, raise alerts.", "Every agent on day one."),
        ("L1 Diagnose", "Explain root cause with evidence; recommend a fix.", "Default level for most problems."),
        ("L2 Act with approval", "Run a runbook step after a human clicks approve.", "Restarts, backfills, resuming tasks."),
        ("L3 Act within bounds", "Run a pre-approved runbook step automatically, once, then escalate.",
         "Producer restart, alert suppression on closed markets."),
    ], [1.4, 3.6, 2.5])]))

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
    st.append(P(f"{len(cat.agents)} roles, each with one job. Each is filled first by an existing tool (named in its "
                "tools column) plus our checks; an AI assistant is added only where a human would otherwise do "
                "repetitive diagnosis or drafting. ANALYST is the Cortex Agent the repo already defines in sql/10_agent."))
    st.append(grid(["Agent", "Owns", "Tools it is given"],
                   [(f"{a.code}<br/><font name='Body' size='7'>{escape(a.name)}</font>", escape(a.owns), escape(a.tools))
                    for a in cat.agents], [1.35, 2.25, 3.9]))

    st.append(PageBreak())
    st.append(P(f"The problems ({n_problems}), stage by stage", "h1"))
    st.append(P("Each row gives the problem as it shows up, who feels it, how the assigned agent handles it, and the "
                "guardrail or human step that keeps the agent safe."))
    for stage in cat.stages:
        st.append(P(f"{stage.id}. {escape(stage.name)}", "h2"))
        rows = [(p.id,
                 f"<b>{escape(p.title)}.</b> {escape(p.symptom)}" + (" <i>(SQL example in the patterns section)</i>" if p.bad_sql else ""),
                 escape(p.who), rich(p.solution, codes), escape(p.guardrail))
                for p in stage.problems]
        st.append(grid(["#", "Problem and how it shows up", "Who", "How the agent solves it", "Guardrail"],
                       rows, [0.38, 2.35, 0.62, 2.65, 1.5]))
        st.append(Spacer(1, 4))

    st.append(PageBreak())
    st.append(P(f"SQL patterns the agents learn ({len(sql_problems)})", "h1"))
    st.append(P("Each pair is a real mistake and its fix, written against this repo's tables where possible. SQLCOACH "
                "uses them as reference knowledge when reviewing SQL, and each pair is also an eval case: the agent "
                "gets the bad query and passes only if it names the right problem and its rewrite returns exactly what "
                "the fixed query returns on seeded test data."))
    code_rows = [(p.id, f"<b>{escape(p.title)}</b>",
                  escape(p.bad_sql.rstrip()).replace("\n", "<br/>").replace("  ", "&nbsp;&nbsp;"),
                  escape(p.good_sql.rstrip()).replace("\n", "<br/>").replace("  ", "&nbsp;&nbsp;"))
                 for p in sql_problems]
    st.append(grid(["#", "Problem", "Mistake", "Fix"],
                   [(a, b, Paragraph(c, S["code"]), Paragraph(d, S["code"])) for a, b, c, d in code_rows],
                   [0.38, 1.12, 3.0, 3.0]))

    st.append(PageBreak())
    st.append(P("How each agent is trained and tested", "h1"))
    st.append(P("Scenarios reuse what the repo already has: generate_sample_data.py and generate_sample_news.py "
                "produce clean data, a small fault-injection layer corrupts it in known ways, and "
                "replay_sample_data.py plays it through Kafka. Every scenario has an expected diagnosis, so it can be "
                "scored."))
    st.append(grid(["Agent", "Knowledge it is given", "Training scenarios", "Pass criteria (evals)"],
                   [(t.agent, escape(t.knowledge), escape(t.scenarios), escape(t.pass_criteria)) for t in cat.training],
                   [0.85, 2.0, 2.45, 2.2]))

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
            "can be triggered on demand, and seed test data so every bad/good SQL pair gives a different answer.",
            "<b>Step 2: L0/L1 observers.</b> WATCH, DQ, GUARD, SCALE (observe only) and SQLCOACH (review only) first, read-only. They catch the problems that "
            "silently damage data.",
            "<b>Step 3: analyst side.</b> ANALYST evals against the sql/08 twins, then CURATOR for the semantic model.",
            "<b>Step 4: repair agents.</b> DOCTOR, XFORM, RELEASE and SCALE actions (scaling, catch-up, deploys), approval-gated (L2).",
            "<b>Step 5: TRIAGE</b> once the specialists are reliable enough to call as tools.",
        ]),
    ]))

    doc.build(st, onFirstPage=on_page, onLaterPages=on_page)
    logger.info("wrote %s (%d problems, %d stages, %d SQL pairs)", out, n_problems, len(cat.stages), len(sql_problems))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    cat = load_catalog(args.catalog)
    register_fonts()
    build(args.out, cat)


if __name__ == "__main__":
    main()
