"""Safety rules of the pipeline doctor that hold without Snowflake or a model."""

import pytest

from glue.doctor import RUNBOOK, TOOLS, PipelineDoctor, load_catalog
from glue.guardrails import GuardrailViolation, check_sql

CLONE = "MARKET_AGENT_CI_TEST"
CLONE_TABLES = frozenset({f"{CLONE}.SILVER.BARS", f"{CLONE}.GOLD.FCT_BARS"})


def test_refuses_production_database():
    with pytest.raises(ValueError):
        PipelineDoctor("MARKET_AGENT")


@pytest.mark.parametrize("action", list(RUNBOOK))
def test_runbook_sql_only_targets_the_given_database(action):
    for stmt in RUNBOOK[action]["sql"]:
        assert "{db}" in stmt
        assert "MARKET_AGENT." not in stmt.format(db=CLONE)


def test_escalate_changes_nothing():
    assert RUNBOOK["escalate"]["sql"] == [] and RUNBOOK["escalate"]["rebuild"] is False


def test_model_can_only_name_runbook_actions():
    submit = next(t for t in TOOLS if t["function"]["name"] == "submit_diagnosis")
    assert submit["function"]["parameters"]["properties"]["action"]["enum"] == list(RUNBOOK)


@pytest.mark.parametrize("sql,code", [
    ("DELETE FROM MARKET_AGENT_CI_TEST.SILVER.BARS", "NOT_READ_ONLY"),
    ("SELECT * FROM MARKET_AGENT.SILVER.BARS", "TABLE_NOT_ALLOWED"),          # production
    ("SELECT * FROM MARKET_AGENT_CI_TEST.BRONZE.RAW_BARS", "TABLE_NOT_ALLOWED"),
    ("SELECT 1; DROP TABLE MARKET_AGENT_CI_TEST.SILVER.BARS", "MULTIPLE_STATEMENTS"),
])
def test_doctor_sql_is_read_only_and_clone_only(sql, code):
    with pytest.raises(GuardrailViolation) as e:
        check_sql(sql, row_limit=20, allowed_tables=CLONE_TABLES)
    assert e.value.code == code


def test_doctor_sql_allows_clone_reads_with_cap():
    checked = check_sql("SELECT symbol, COUNT(*) FROM MARKET_AGENT_CI_TEST.SILVER.BARS GROUP BY 1",
                        row_limit=20, allowed_tables=CLONE_TABLES)
    assert checked.sql.endswith("LIMIT 20")


def test_catalog_has_every_problem():
    assert len(load_catalog()) == 158
