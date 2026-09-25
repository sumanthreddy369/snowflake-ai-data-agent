"""
Pydantic models for the three record types this pipeline moves onto Kafka and
into Snowflake Bronze (sql/02_bronze/bronze_tables.sql). Centralizing the
schema here means alpaca_stream_producer.py (live), generate_sample_data.py
(offline fallback), replay_sample_data.py, and backfill_historical.py all
validate against the same contract instead of passing around raw dicts.
"""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class TradeRecord(BaseModel):
    trade_id: str
    symbol: str
    price: float = Field(gt=0)
    size: int = Field(gt=0)
    exchange_code: str | None = None
    conditions: str = ""
    trade_ts: datetime

    @field_validator("trade_ts")
    @classmethod
    def must_be_timezone_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("trade_ts must be timezone-aware (use UTC)")
        return v


class BarRecord(BaseModel):
    symbol: str
    bar_ts: datetime
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: int = Field(ge=0)
    vwap: float | None = None
    trade_count: int | None = None

    @field_validator("bar_ts")
    @classmethod
    def must_be_timezone_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("bar_ts must be timezone-aware (use UTC)")
        return v

    @field_validator("high")
    @classmethod
    def high_is_highest(cls, v, info):
        low = info.data.get("low")
        if low is not None and v < low:
            raise ValueError(f"high ({v}) is below low ({low})")
        return v


class SymbolRecord(BaseModel):
    symbol: str
    company_name: str
    sector: str
    exchange: str
    is_active: bool = True
