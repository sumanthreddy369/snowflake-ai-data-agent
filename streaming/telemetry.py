"""
Optional OpenTelemetry metrics and traces for the streaming scripts.

Off unless OTEL_EXPORTER_OTLP_ENDPOINT is set (http://localhost:14318 with
infra/local/docker-compose.yml running): with it unset, every call below is a
no-op and no OpenTelemetry package is even imported, so the offline sample
workflow and CI need nothing extra.

Metrics (Prometheus names after the collector's conversion):
  market_messages_sent_total{topic}     messages published to Kafka
  market_dlq_messages_total{source}     messages routed to the DLQ
  market_event_lag_seconds              event time -> publish time (live feed only)
  market_last_message_unixtime          when the last message was published

Uses OTLP over HTTP rather than gRPC to avoid pulling grpc and
protobuf version constraints into the streaming environment.
"""

import atexit
import os
import time
from datetime import datetime, timezone


class Telemetry:
    def __init__(self, service_name: str):
        self.enabled = bool(os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"))
        self._last_message = 0.0
        if not self.enabled:
            return

        from opentelemetry import metrics, trace
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.metrics import Observation
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({"service.name": service_name, "service.namespace": "market-agent"})
        meter_provider = MeterProvider(
            resource=resource,
            metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter(), export_interval_millis=10_000)],
        )
        tracer_provider = TracerProvider(resource=resource)
        tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        metrics.set_meter_provider(meter_provider)
        trace.set_tracer_provider(tracer_provider)
        # Flush buffered metrics/spans when the script exits.
        atexit.register(meter_provider.shutdown)
        atexit.register(tracer_provider.shutdown)

        meter = metrics.get_meter("market_agent.streaming")
        self.tracer = trace.get_tracer("market_agent.streaming")
        self._sent = meter.create_counter("market_messages_sent", description="Messages published to Kafka")
        self._dlq = meter.create_counter("market_dlq_messages", description="Messages routed to the DLQ")
        self._lag = meter.create_histogram(
            "market_event_lag", unit="s", description="Seconds from event time to publish time")
        meter.create_observable_gauge(
            "market_last_message_unixtime",
            callbacks=[lambda _options: [Observation(self._last_message)] if self._last_message else []],
            description="Unix time of the last published message",
        )

    def sent(self, topic: str, event_ts: datetime | None = None) -> None:
        if not self.enabled:
            return
        self._last_message = time.time()
        self._sent.add(1, {"topic": topic})
        if event_ts is not None:
            lag = (datetime.now(timezone.utc) - event_ts).total_seconds()
            self._lag.record(lag)

    def dlq(self, source: str) -> None:
        if self.enabled:
            self._dlq.add(1, {"source": source})
