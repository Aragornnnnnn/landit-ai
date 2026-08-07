# FastAPI와 Python runtime 메트릭을 OpenTelemetry로 내보내는 모듈
import os
from collections.abc import Callable

from fastapi import FastAPI
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.system_metrics import SystemMetricsInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    MetricReader,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.metrics.view import DropAggregation, View
from opentelemetry.sdk.resources import Resource

from app.core.config import Settings


_HTTP_ATTRIBUTE_KEYS = {
    "error.type",
    "http.method",
    "http.request.method",
    "http.response.status_code",
    "http.route",
    "http.status_code",
}

_RUNTIME_METRICS = {
    "process.cpu.time": ["user", "system"],
    "process.cpu.utilization": None,
    "process.memory.usage": None,
    "process.memory.virtual": None,
    "process.thread.count": None,
    "cpython.gc.collections": None,
    "cpython.gc.collected_objects": None,
    "cpython.gc.uncollectable_objects": None,
}


def init_metrics(
    fastapi_app: FastAPI,
    settings: Settings,
    *,
    metric_reader: MetricReader | None = None,
) -> MeterProvider | None:
    if not settings.otel_metrics_enabled:
        return None

    resolved_reader = metric_reader or _create_otlp_metric_reader(settings)
    meter_provider = MeterProvider(
        metric_readers=[resolved_reader],
        resource=Resource.create(
            {
                "service.name": settings.otel_service_name,
                "service.namespace": "landit",
                "service.version": settings.app_version,
                "deployment.environment.name": settings.app_env,
            },
        ),
        shutdown_on_exit=False,
        views=_metric_views(),
    )

    os.environ.setdefault("OTEL_SEMCONV_STABILITY_OPT_IN", "http")
    FastAPIInstrumentor.instrument_app(
        fastapi_app,
        meter_provider=meter_provider,
        excluded_urls=r"/health(?:\?.*)?$",
        http_capture_headers_server_request=[],
        http_capture_headers_server_response=[],
    )
    system_metrics = SystemMetricsInstrumentor(config=_RUNTIME_METRICS)
    system_metrics.instrument(meter_provider=meter_provider)

    fastapi_app.state.otel_meter_provider = meter_provider
    fastapi_app.router.add_event_handler(
        "shutdown",
        _shutdown_metrics(fastapi_app, system_metrics, meter_provider),
    )
    return meter_provider


def _create_otlp_metric_reader(settings: Settings) -> MetricReader:
    endpoint = settings.otel_exporter_otlp_endpoint
    headers = settings.otel_exporter_otlp_headers
    if (
        not endpoint
        or not endpoint.strip()
        or not headers
        or not headers.get_secret_value().strip()
    ):
        raise RuntimeError(
            "OTEL_EXPORTER_OTLP_ENDPOINT and OTEL_EXPORTER_OTLP_HEADERS are required "
            "when OTEL_METRICS_ENABLED is true.",
        )

    return PeriodicExportingMetricReader(OTLPMetricExporter())


def _metric_views() -> list[View]:
    views = [
        View(
            instrument_name="http.server.request.duration",
            attribute_keys=_HTTP_ATTRIBUTE_KEYS,
        ),
        View(
            instrument_name="http.server.duration",
            attribute_keys=_HTTP_ATTRIBUTE_KEYS,
        ),
    ]
    for instrument_name in (
        "http.server.active_requests",
        "http.server.request.body.size",
        "http.server.request.size",
        "http.server.response.body.size",
        "http.server.response.size",
    ):
        views.append(
            View(
                instrument_name=instrument_name,
                aggregation=DropAggregation(),
            ),
        )
    return views


def _shutdown_metrics(
    fastapi_app: FastAPI,
    system_metrics: SystemMetricsInstrumentor,
    meter_provider: MeterProvider,
) -> Callable[[], None]:
    def shutdown() -> None:
        FastAPIInstrumentor.uninstrument_app(fastapi_app)
        system_metrics.uninstrument()
        meter_provider.shutdown()

    return shutdown
