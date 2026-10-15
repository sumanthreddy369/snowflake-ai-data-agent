"""
Guardrails for SQL written by an LLM, checked before anything reaches Snowflake.

This is the deterministic half of the guardrail gateway
(docs/glue-and-guardrails.md §4): the model can propose any text, but only a
single, read-only query over allow-listed Gold objects is ever executed, and
always with a row cap. The database adds the second layer -- the query runs as
ANALYST_AGENT under the row access policy and a statement timeout -- so a
mistake that got past this module would still be limited by Snowflake.

Parsing uses sqlglot (Snowflake dialect) rather than regexes, so tricks like
comments, string literals containing keywords, or stacked statements are
judged on the parsed query, not its surface text.
"""

from dataclasses import dataclass

import sqlglot
from sqlglot import exp

# The only objects the analyst agent may read: the governed Gold star schema.
ALLOWED_TABLES = frozenset({
    "MARKET_AGENT.GOLD.FCT_BARS",
    "MARKET_AGENT.GOLD.FCT_TRADES",
    "MARKET_AGENT.GOLD.DIM_SYMBOLS",
    "MARKET_AGENT.GOLD.DIM_DATE",
})
DEFAULT_ROW_LIMIT = 1000

# Statement types that change data, privileges or session state.
_FORBIDDEN_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Create, exp.Drop, exp.Alter,
    exp.TruncateTable, exp.Grant, exp.Command, exp.Use, exp.Set, exp.Copy,
)


class GuardrailViolation(Exception):
    """Raised when proposed SQL breaks a rule; `code` is stable for metrics and audit."""

    def __init__(self, code: str, reason: str):
        super().__init__(f"{code}: {reason}")
        self.code = code
        self.reason = reason


@dataclass(frozen=True)
class CheckedSql:
    sql: str                  # what will actually run (row cap applied)
    tables: tuple[str, ...]   # fully qualified objects it reads


def _qualified(table: exp.Table) -> str:
    parts = [p for p in (table.catalog, table.db, table.name) if p]
    return ".".join(parts).upper()


def check_sql(sql: str, row_limit: int = DEFAULT_ROW_LIMIT) -> CheckedSql:
    """Validate LLM-proposed SQL; return the exact statement to run, or raise."""
    text = (sql or "").strip().rstrip(";").strip()
    if not text:
        raise GuardrailViolation("EMPTY", "no SQL was proposed")
    try:
        statements = sqlglot.parse(text, read="snowflake")
    except sqlglot.errors.ParseError as e:
        raise GuardrailViolation("UNPARSEABLE", str(e).splitlines()[0]) from e
    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        raise GuardrailViolation("MULTIPLE_STATEMENTS", f"{len(statements)} statements; exactly one SELECT is allowed")
    tree = statements[0]

    if not isinstance(tree, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        raise GuardrailViolation("NOT_READ_ONLY", f"{type(tree).__name__} statements are not allowed; only SELECT")
    for node in tree.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            raise GuardrailViolation("NOT_READ_ONLY", f"contains a {type(node).__name__} operation")

    cte_names = {cte.alias_or_name.upper() for cte in tree.find_all(exp.CTE)}
    tables = []
    for table in tree.find_all(exp.Table):
        name = _qualified(table)
        if not name or name in cte_names:
            continue
        if name not in ALLOWED_TABLES:
            raise GuardrailViolation(
                "TABLE_NOT_ALLOWED",
                f"{name} is not an allowed source; use fully qualified Gold tables: {', '.join(sorted(ALLOWED_TABLES))}")
        tables.append(name)
    if not tables:
        raise GuardrailViolation("NO_ALLOWED_TABLE", "the query must read from at least one Gold table")

    # Row cap: wrap rather than edit, so the model's own LIMIT/ORDER BY is untouched.
    capped = f"SELECT * FROM (\n{tree.sql(dialect='snowflake')}\n) LIMIT {int(row_limit)}"
    return CheckedSql(sql=capped, tables=tuple(sorted(set(tables))))
