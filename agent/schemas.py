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
