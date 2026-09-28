"""Pydantic contracts for the Cortex Analyst REST client (cortex_client.py)."""

from pydantic import BaseModel


class CortexAnalystRequest(BaseModel):
    question: str
    semantic_model_file: str  # stage path, e.g. "@MARKET_AGENT.GOLD.SEMANTIC_MODELS/semantic_model.yaml"


class CortexAnalystResponse(BaseModel):
    request_id: str | None = None
    text: str | None = None
    sql: str | None = None
    suggestions: list[str] | None = None
    is_ambiguous: bool = False


class NewsCitation(BaseModel):
    url: str | None = None
    headline: str | None = None


class AgentRunResponse(BaseModel):
    """Response from the Cortex Agent (sql/10_agent/cortex_agent.sql), which
    can invoke the analyst tool, the search tool, or both per question."""

    request_id: str | None = None
    text: str | None = None
    sql: str | None = None
    tools_used: list[str] = []
    citations: list[NewsCitation] = []
