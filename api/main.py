"""
A thin FastAPI service exposing this project's agent as an HTTP API -- for
when an external service layer is beneficial (e.g. a future non-Snowflake
frontend, a webhook, or a service outside this account calling in). The
Streamlit app (ui/streamlit_app.py) is the Snowflake-native UI; this is the
"plain HTTP" option for everything else.

Like every other entry point in this project, this does not add its own
access control beyond what the underlying PAT/role already has -- it's a
pass-through to cortex_agent_client.py, so the same Row Access Policy and
15-minute-delay rule apply regardless of how the question arrives.

Run: uvicorn main:app --reload
Set OTEL_EXPORTER_OTLP_ENDPOINT to export request metrics and traces (OpenTelemetry).
"""

import os
import sys

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

sys.path.insert(0, "../agent")
from cortex_agent_client import ask_market_data_agent  # noqa: E402
from cortex_client import ask_cortex_analyst  # noqa: E402

app = FastAPI(
    title="Market Data AI Agent API",
    description="HTTP layer over the Cortex Agent / Cortex Analyst clients. See agent/README.md for governance notes.",
)

if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
    # Request count, latency and error metrics plus a trace per request, sent
    # to the OTel Collector (infra/local). Off by default so nothing changes
    # when the observability stack isn't running.
    from opentelemetry import metrics, trace
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    _resource = Resource.create({"service.name": "market-agent-api", "service.namespace": "market-agent"})
    metrics.set_meter_provider(MeterProvider(
        resource=_resource, metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter())]))
    _tracer_provider = TracerProvider(resource=_resource)
    _tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(_tracer_provider)
    FastAPIInstrumentor.instrument_app(app)


class QuestionRequest(BaseModel):
    question: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/ask")
def ask(request: QuestionRequest):
    """Routes through the Cortex Agent (may use analyst, search, or both)."""
    try:
        result = ask_market_data_agent(request.question)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"agent call failed: {e}") from e
    return result.model_dump()


@app.post("/ask/analyst-only")
def ask_analyst_only(request: QuestionRequest):
    """Skips agent tool-routing; goes straight to Cortex Analyst."""
    try:
        result = ask_cortex_analyst(request.question)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"analyst call failed: {e}") from e
    return result.model_dump()
