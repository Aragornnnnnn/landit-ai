# OpenTelemetry 메트릭 계측과 외부 전송 경계를 검증하는 unittest 모듈
import os
import unittest
import warnings
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from app.core.config import Settings
from app.core.observability import init_metrics


def make_settings(**overrides):
    return Settings(_env_file=None, **overrides)


def make_client(app):
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Using `httpx` with `starlette.testclient` is deprecated.*",
        )
        from fastapi.testclient import TestClient

        return TestClient(app)


def collected_metrics(metric_reader):
    metrics_data = metric_reader.get_metrics_data()
    return {
        metric.name: metric
        for resource_metrics in metrics_data.resource_metrics
        for scope_metrics in resource_metrics.scope_metrics
        for metric in scope_metrics.metrics
    }


class ObservabilitySettingsTests(unittest.TestCase):
    def test_metrics_are_disabled_without_explicit_environment_setting(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = make_settings()

        self.assertFalse(settings.otel_metrics_enabled)
        self.assertEqual(settings.otel_service_name, "landit-ai")
        self.assertIsNone(settings.otel_exporter_otlp_endpoint)
        self.assertIsNone(settings.otel_exporter_otlp_headers)

    def test_standard_otlp_environment_variables_are_read(self):
        with patch.dict(
            os.environ,
            {
                "OTEL_METRICS_ENABLED": "true",
                "OTEL_SERVICE_NAME": "landit-ai-observability-test",
                "OTEL_EXPORTER_OTLP_ENDPOINT": "https://otlp.example/otlp",
                "OTEL_EXPORTER_OTLP_HEADERS": "Authorization=test-placeholder",
            },
            clear=True,
        ):
            settings = make_settings()

        self.assertTrue(settings.otel_metrics_enabled)
        self.assertEqual(
            settings.otel_service_name,
            "landit-ai-observability-test",
        )
        self.assertEqual(
            settings.otel_exporter_otlp_endpoint,
            "https://otlp.example/otlp",
        )
        self.assertIsNotNone(settings.otel_exporter_otlp_headers)
        self.assertEqual(
            settings.otel_exporter_otlp_headers.get_secret_value(),
            "Authorization=test-placeholder",
        )


class MetricsInitializationTests(unittest.TestCase):
    def test_disabled_metrics_do_not_create_an_otlp_exporter(self):
        app = FastAPI()

        with patch("app.core.observability.OTLPMetricExporter") as exporter:
            meter_provider = init_metrics(app, make_settings())

        self.assertIsNone(meter_provider)
        exporter.assert_not_called()

    def test_enabled_external_export_requires_endpoint_and_headers(self):
        app = FastAPI()

        with self.assertRaisesRegex(
            RuntimeError,
            "OTEL_EXPORTER_OTLP_ENDPOINT.*OTEL_EXPORTER_OTLP_HEADERS",
        ):
            init_metrics(app, make_settings(otel_metrics_enabled=True))

    def test_collects_only_templated_http_and_process_gc_metrics(self):
        app = FastAPI()

        @app.get("/health")
        def health():
            return {"status": "ok"}

        @app.get("/items/{item_id}")
        def read_item(item_id: str, fail: bool = False):
            if fail:
                raise HTTPException(status_code=503, detail="failed")
            return {"itemId": item_id}

        metric_reader = InMemoryMetricReader()
        meter_provider = init_metrics(
            app,
            make_settings(
                otel_metrics_enabled=True,
                otel_service_name="landit-ai-test",
                app_env="test",
            ),
            metric_reader=metric_reader,
        )

        with make_client(app) as client:
            client.get(
                "/items/user-123?token=secret-query",
                headers={"Authorization": "secret-header"},
            )
            client.get("/items/user-456?fail=true")
            client.get("/health")
            client.get("/not-found/user-789?token=secret-unmatched")

        metrics = collected_metrics(metric_reader)
        resource_attributes = dict(
            metric_reader.get_metrics_data().resource_metrics[0].resource.attributes,
        )
        http_metric = metrics.get("http.server.request.duration") or metrics.get(
            "http.server.duration",
        )

        self.assertIsNotNone(meter_provider)
        self.assertIsNotNone(http_metric)
        self.assertEqual(resource_attributes["service.name"], "landit-ai-test")
        self.assertEqual(
            resource_attributes["deployment.environment.name"],
            "test",
        )
        self.assertNotIn("deployment.environment", resource_attributes)

        http_points = list(http_metric.data.data_points)
        templated_points = [
            point
            for point in http_points
            if point.attributes.get("http.route") == "/items/{item_id}"
        ]
        self.assertEqual(
            {
                point.attributes.get("http.response.status_code")
                for point in templated_points
            },
            {200, 503},
        )
        self.assertTrue(all(point.count == 1 for point in templated_points))

        serialized_attributes = repr(
            [dict(point.attributes) for point in http_points],
        )
        self.assertNotIn("/health", serialized_attributes)
        self.assertNotIn("not-found", serialized_attributes)
        self.assertNotIn("user-123", serialized_attributes)
        self.assertNotIn("user-456", serialized_attributes)
        self.assertNotIn("user-789", serialized_attributes)
        self.assertNotIn("secret-query", serialized_attributes)
        self.assertNotIn("secret-unmatched", serialized_attributes)
        self.assertNotIn("secret-header", serialized_attributes)

        self.assertIn("process.cpu.time", metrics)
        self.assertIn("process.memory.usage", metrics)
        self.assertIn("process.memory.virtual", metrics)
        self.assertIn("cpython.gc.collections", metrics)
        self.assertIn("cpython.gc.collected_objects", metrics)
        self.assertIn("cpython.gc.uncollectable_objects", metrics)
        self.assertFalse(any(name.startswith("system.") for name in metrics))


if __name__ == "__main__":
    unittest.main()
