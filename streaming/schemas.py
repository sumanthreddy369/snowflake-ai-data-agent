"""
Pydantic models for the three record types this pipeline moves onto Kafka and
into Snowflake Bronze (sql/02_bronze/bronze_tables.sql). Centralizing the
schema here means alpaca_stream_producer.py (live), generate_sample_data.py
(offline fallback), replay_sample_data.py, and backfill_historical.py all
validate against the same contract instead of passing around raw dicts.
"""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator


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

    @model_validator(mode="after")
    def ohlc_is_internally_consistent(self):
        # A field_validator on `high` alone can't see `low` if `low` is
        # declared later in the model (Pydantic validates fields in
        # declaration order, so `low` isn't parsed yet) -- this has to be a
        # model-level check to see every field regardless of order.
        if self.high < self.low:
            raise ValueError(f"high ({self.high}) is below low ({self.low})")
        if self.high < self.open or self.high < self.close:
            raise ValueError(f"high ({self.high}) is below open/close")
        if self.low > self.open or self.low > self.close:
            raise ValueError(f"low ({self.low}) is above open/close")
        return self


class SymbolRecord(BaseModel):
    symbol: str
    company_name: str
    sector: str
    exchange: str
    is_active: bool = True
