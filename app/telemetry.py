"""Cinema CI — OpenTelemetry Instrumentation for Grafana Cloud.

Provides metrics (Prometheus), traces (Tempo), and structured logs (Loki)
for Cinema CI workflows and autonomous agent operations.
"""

from __future__ import annotations

import os
import time
import urllib.parse
from typing import Any

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry._logs import set_logger_provider, get_logger_provider, get_logger, LogRecord as APILogRecord

try:
    from opentelemetry.sdk._logs import LoggerProvider, LogRecord
except ImportError:
    from opentelemetry.sdk._logs import LoggerProvider
    from opentelemetry.sdk._logs._internal import LogRecord
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

from app.models import Build, TestResult, TestStatus

_latest_test_pass_ratio: dict[str, float] = {}
_latest_release_ready: dict[str, int] = {}
_latest_active_regressions: dict[str, int] = {}

_meter = None
_tracer = None
_logger_provider = None
_tracer_provider = None

_release_ready = None
_active_regressions = None
_builds_total = None
_repairs_total = None
_repair_success_total = None
_build_operations = None
_assets_rebuilt = None
_assets_reused = None
_operations_avoided = None
_creative_tests_total = None
_technical_tests_total = None
_validation_failures_total = None

# In-memory structured logs buffer for the UI / API
_recent_logs: list[dict[str, Any]] = []
_MAX_LOG_HISTORY = 200


def _test_pass_ratio_callback(options):
    from opentelemetry.metrics import Observation
    observations = []
    for project_id, ratio in _latest_test_pass_ratio.items():
        observations.append(Observation(ratio, {"project_id": project_id}))
    return observations


def setup_telemetry() -> None:
    """Initialize OpenTelemetry metrics, traces, and logs exporting to Grafana Cloud."""
    global _meter, _tracer, _logger_provider, _tracer_provider
    global _release_ready, _active_regressions, _builds_total, _repairs_total, _repair_success_total
    global _build_operations, _assets_rebuilt, _assets_reused, _operations_avoided
    global _creative_tests_total, _technical_tests_total, _validation_failures_total

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    headers_str = os.getenv("OTEL_EXPORTER_OTLP_HEADERS", "")

    headers_dict = {}
    if headers_str:
        for pair in headers_str.split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                k = urllib.parse.unquote(k)
                v = urllib.parse.unquote(v)
                headers_dict[k] = v

    resource = Resource.create({"service.name": "cinema-ci"})

    # Set up traces (Grafana Tempo)
    traces_endpoint = f"{endpoint}/v1/traces" if endpoint else None
    trace_exporter = OTLPSpanExporter(
        endpoint=traces_endpoint,
        headers=headers_dict
    )
    _tracer_provider = TracerProvider(resource=resource)
    _tracer_provider.add_span_processor(BatchSpanProcessor(trace_exporter))
    trace.set_tracer_provider(_tracer_provider)
    _tracer = trace.get_tracer("cinema-ci")

    # Set up metrics (Grafana Prometheus)
    metrics_endpoint = f"{endpoint}/v1/metrics" if endpoint else None
    metric_exporter = OTLPMetricExporter(
        endpoint=metrics_endpoint,
        headers=headers_dict
    )
    metric_reader = PeriodicExportingMetricReader(metric_exporter, export_interval_millis=10000)
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)

    _meter = metrics.get_meter("cinema-ci")

    _release_ready = _meter.create_up_down_counter(
        "cinema_ci_release_ready",
        description="Tracks if the release is ready (1) or blocked (0)"
    )

    _meter.create_observable_gauge(
        "cinema_ci_test_pass_ratio",
        callbacks=[_test_pass_ratio_callback],
        description="Ratio of passed tests to total tests"
    )

    _active_regressions = _meter.create_up_down_counter(
        "cinema_ci_active_regressions",
        description="Number of active regressions"
    )

    _builds_total = _meter.create_counter(
        "cinema_ci_builds_total",
        description="Total number of builds"
    )

    _repairs_total = _meter.create_counter(
        "cinema_ci_repairs_total",
        description="Total number of automated repairs attempted"
    )

    _repair_success_total = _meter.create_counter(
        "cinema_ci_repair_success_total",
        description="Total number of successful automated repairs"
    )

    _build_operations = _meter.create_counter(
        "cinema_ci_build_operations",
        description="Total build operations executed"
    )

    _assets_rebuilt = _meter.create_counter(
        "cinema_ci_assets_rebuilt",
        description="Total assets rebuilt"
    )

    _assets_reused = _meter.create_counter(
        "cinema_ci_assets_reused",
        description="Total assets reused from baseline"
    )

    _operations_avoided = _meter.create_counter(
        "cinema_ci_generation_operations_avoided",
        description="Total generation operations avoided by Cinema CI"
    )

    _creative_tests_total = _meter.create_counter(
        "cinema_ci_creative_tests_total",
        description="Total creative test evaluations"
    )

    _technical_tests_total = _meter.create_counter(
        "cinema_ci_technical_tests_total",
        description="Total technical test evaluations"
    )

    _validation_failures_total = _meter.create_counter(
        "cinema_ci_validation_failures_total",
        description="Total validation failures detected"
    )

    # Set up logs
    logs_endpoint = f"{endpoint}/v1/logs" if endpoint else None
    log_exporter = OTLPLogExporter(
        endpoint=logs_endpoint,
        headers=headers_dict
    )
    _logger_provider = LoggerProvider(resource=resource)
    _logger_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))
    set_logger_provider(_logger_provider)


def record_build_completed(project_id: str, build: Build) -> None:
    """Record metrics when a build is completed."""
    if not _builds_total:
        return
    
    _builds_total.add(1, {"project_id": project_id, "result": build.status.value})

    new_release_ready = 1 if build.release_ready else 0
    old_release_ready = _latest_release_ready.get(project_id, 0)
    if new_release_ready != old_release_ready:
        delta = new_release_ready - old_release_ready
        _release_ready.add(delta, {"project_id": project_id})
        _latest_release_ready[project_id] = new_release_ready

    new_regressions = build.regressions
    old_regressions = _latest_active_regressions.get(project_id, 0)
    if new_regressions != old_regressions:
        delta = new_regressions - old_regressions
        _active_regressions.add(delta, {"project_id": project_id})
        _latest_active_regressions[project_id] = new_regressions

    # Incremental operations metrics
    if _assets_rebuilt and build.operations_rebuilt:
        _assets_rebuilt.add(build.operations_rebuilt, {"project_id": project_id})
    if _assets_reused and build.operations_reused:
        _assets_reused.add(build.operations_reused, {"project_id": project_id})
    if _operations_avoided and build.operations_avoided:
        _operations_avoided.add(build.operations_avoided, {"project_id": project_id})
    if _build_operations and build.operations_total:
        _build_operations.add(build.operations_total, {"project_id": project_id})


def record_test_results(project_id: str, results: list[TestResult]) -> None:
    """Record test results to update the pass ratio gauge and category counters."""
    if not results:
        _latest_test_pass_ratio[project_id] = 0.0
        return
    passed = sum(1 for r in results if r.status == TestStatus.PASS)
    ratio = passed / len(results)
    _latest_test_pass_ratio[project_id] = ratio

    creative_count = sum(1 for r in results if r.category == "creative")
    technical_count = sum(1 for r in results if r.category == "technical")
    failures = sum(1 for r in results if r.status in (TestStatus.FAIL, TestStatus.REGRESSION))

    if _creative_tests_total and creative_count:
        _creative_tests_total.add(creative_count, {"project_id": project_id})
    if _technical_tests_total and technical_count:
        _technical_tests_total.add(technical_count, {"project_id": project_id})
    if _validation_failures_total and failures:
        _validation_failures_total.add(failures, {"project_id": project_id})


def record_repair(project_id: str, success: bool) -> None:
    """Record an automated repair attempt."""
    if not _repairs_total:
        return
    _repairs_total.add(1, {"project_id": project_id})
    if success:
        _repair_success_total.add(1, {"project_id": project_id})


def get_tracer():
    """Get the active OpenTelemetry tracer."""
    global _tracer
    if not _tracer:
        _tracer = trace.get_tracer("cinema-ci")
    return _tracer


def emit_log(event: str, attributes: dict[str, Any]) -> None:
    """Send a structured log to Grafana via OTel logging and append to local memory buffer."""
    import datetime
    logger = get_logger("cinema-ci")
    now = time.time()
    timestamp_ns = int(now * 1e9)
    iso_time = datetime.datetime.now(datetime.timezone.utc).isoformat()
    record = APILogRecord(
        timestamp=timestamp_ns,
        body=event,
        attributes=attributes,
        severity_number=9,
        severity_text="INFO"
    )
    logger.emit(record)

    # Maintain in-memory log buffer for UI inspection
    log_entry = {
        "timestamp": iso_time,
        "timestamp_ns": timestamp_ns,
        "event_type": event,
        "event": event,
        "build_id": attributes.get("cinema.build_id") or attributes.get("build_id") or "",
        "scope": attributes.get("cinema.scope") or attributes.get("scope") or "global",
        "status": attributes.get("cinema.status") or attributes.get("status") or "INFO",
        "message": attributes.get("message") or attributes.get("cinema.selection.reason") or event,
        "details": dict(attributes),
        "attributes": dict(attributes),
        "service_name": "cinema-ci",
    }
    _recent_logs.append(log_entry)
    if len(_recent_logs) > _MAX_LOG_HISTORY:
        _recent_logs.pop(0)


def get_recent_logs(limit: int = 50, filter_event: str | None = None) -> list[dict[str, Any]]:
    """Retrieve recent structured logs emitted to Grafana Loki."""
    logs = list(_recent_logs)
    if not logs:
        try:
            from app.engine import get_all_builds
            from app.contract import load_contract
            contract_path = os.getenv("CINEMA_CONTRACT_PATH", "cinema.yaml")
            c = load_contract(contract_path)
            project_id = c.project.id if c else "cafe-envelope"
            builds = get_all_builds(project_id)
            for b in reversed(builds[:6]):
                for entry in getattr(b, "logs", []):
                    logs.append({
                        "timestamp": entry.timestamp,
                        "timestamp_ns": int(time.time() * 1e9),
                        "event_type": entry.stage,
                        "event": entry.stage,
                        "build_id": b.build_id,
                        "scope": entry.shot_id or "pipeline",
                        "status": entry.level,
                        "level": entry.level,
                        "message": entry.message,
                        "details": entry.details or {},
                        "attributes": {"cinema.build_id": b.build_id, "cinema.scope": entry.shot_id or "pipeline"},
                        "service_name": "cinema-ci",
                    })
                for tr in getattr(b, "test_results", []):
                    logs.append({
                        "timestamp": b.created_at,
                        "timestamp_ns": int(time.time() * 1e9),
                        "event_type": f"TEST_{tr.category.upper()}",
                        "event": f"TEST_{tr.category.upper()}",
                        "build_id": b.build_id,
                        "scope": tr.scope,
                        "status": tr.status.value,
                        "level": "INFO" if tr.status.value == "PASS" else "WARNING",
                        "message": f"{tr.name}: {tr.summary}",
                        "details": {"test_id": tr.test_id, "score": tr.score},
                        "attributes": {"cinema.build_id": b.build_id, "cinema.scope": tr.scope},
                        "service_name": "cinema-ci",
                    })
                poster_art = next((d for d in b.deliverables if d.artifact_id == "poster"), None)
                if poster_art and poster_art.details:
                    logs.append({
                        "timestamp": b.created_at,
                        "timestamp_ns": int(time.time() * 1e9),
                        "event_type": "RUNTIME_LINEAGE",
                        "event": "RUNTIME_LINEAGE",
                        "build_id": b.build_id,
                        "scope": "poster",
                        "status": "PASS",
                        "level": "INFO",
                        "message": f"Poster generated from {poster_art.details.get('selected_reference', 'shot_03:keyframe:v1')}: {poster_art.details.get('selection_reason', 'Visual composition selected by Gemini')}",
                        "details": poster_art.details,
                        "attributes": {"cinema.build_id": b.build_id, "cinema.scope": "poster"},
                        "service_name": "cinema-ci",
                    })
        except Exception:
            pass

    if filter_event:
        logs = [l for l in logs if l.get("event") == filter_event or l.get("event_type") == filter_event]
    return list(reversed(logs[-limit:]))


def get_telemetry_status(project_id: str = "cafe-envelope") -> dict[str, Any]:
    """Return comprehensive telemetry state across Prometheus, Tempo, Loki, and Grafana MCP."""
    from app.agent.mcp_grafana import _mcp_process, mcp_client

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    grafana_url = os.getenv("GRAFANA_URL", "https://friendlysherbet668.grafana.net")
    prom_uid = os.getenv("PROM_DATASOURCE_UID", "grafanacloud-prom")
    loki_uid = os.getenv("LOKI_DATASOURCE_UID", "grafanacloud-logs")
    tempo_uid = os.getenv("TEMPO_DATASOURCE_UID", "grafanacloud-traces")
    strict_mode = mcp_client.is_strict_mode()
    mcp_running = mcp_client.is_mcp_connected()
    discovered_tools = _mcp_process.get_tool_names() if mcp_running else []

    # Get aggregated metrics from builds
    from app.engine import get_all_builds
    builds = get_all_builds(project_id) if project_id else get_all_builds()

    total_builds = len(builds)
    active_regressions = _latest_active_regressions.get(project_id, sum(b.regressions for b in builds if b.status.value == "BLOCKED"))
    release_ready = _latest_release_ready.get(project_id, 1 if any(b.release_ready for b in builds) else 0)
    
    total_passed = sum(b.tests_passed for b in builds)
    total_tests = sum(b.tests_total for b in builds)
    test_pass_ratio = _latest_test_pass_ratio.get(project_id, (total_passed / total_tests) if total_tests > 0 else 1.0)

    total_rebuilt = sum(b.operations_rebuilt for b in builds)
    total_reused = sum(b.operations_reused for b in builds)
    total_avoided = sum(b.operations_avoided for b in builds)
    total_operations = sum(b.operations_total for b in builds)

    creative_tests = sum(b.creative_tests_total for b in builds)
    technical_tests = sum(b.technical_tests_total for b in builds)
    validation_failures = sum(b.regressions + (b.tests_total - b.tests_passed) for b in builds)
    repairs_total = sum(b.repair_attempts for b in builds)
    repairs_success = sum(1 for b in builds if b.repair_of and b.status.value in ("PASSED", "RELEASE_READY", "RELEASED"))

    return {
        "grafana": {
            "grafana_url": grafana_url,
            "otlp_endpoint": endpoint,
            "datasources": {
                "prometheus": prom_uid,
                "loki": loki_uid,
                "tempo": tempo_uid,
            },
            "mcp": {
                "connected": mcp_running,
                "strict_mode": strict_mode,
                "fallbacks_used": mcp_client.get_fallback_count(),
                "tools_count": len(discovered_tools),
                "tools": discovered_tools,
            },
        },
        "metrics": {
            "cinema_ci_release_ready": {
                "value": release_ready,
                "status": "READY" if release_ready == 1 else "BLOCKED",
                "promql": "cinema_ci_release_ready",
                "description": "Gate status: 1 for Release Ready, 0 for Blocked",
            },
            "cinema_ci_test_pass_ratio": {
                "value": round(test_pass_ratio * 100, 1),
                "promql": "cinema_ci_test_pass_ratio * 100",
                "unit": "%",
                "description": "Ratio of passed tests across all active evaluations",
            },
            "cinema_ci_active_regressions": {
                "value": active_regressions,
                "promql": "cinema_ci_active_regressions",
                "description": "Count of unresolved creative or technical regressions",
            },
            "cinema_ci_builds_total": {
                "value": total_builds,
                "promql": "sum(cinema_ci_builds_total)",
                "description": "Total builds executed through Cinema CI engine",
            },
            "cinema_ci_generation_operations_avoided": {
                "value": total_avoided,
                "promql": "cinema_ci_generation_operations_avoided",
                "description": "Total AI generation operations avoided via deterministic reuse",
            },
            "cinema_ci_assets_reused": {
                "value": total_reused,
                "promql": "cinema_ci_assets_reused",
                "description": "Assets verified with byte-identical SHA-256 reuse",
            },
            "cinema_ci_assets_rebuilt": {
                "value": total_rebuilt,
                "promql": "cinema_ci_assets_rebuilt",
                "description": "Assets rebuilt due to creative change impact",
            },
            "cinema_ci_creative_tests_total": {
                "value": creative_tests,
                "promql": "cinema_ci_creative_tests_total",
                "description": "Multimodal Gemini 3.8 Flash creative contract tests",
            },
            "cinema_ci_technical_tests_total": {
                "value": technical_tests,
                "promql": "cinema_ci_technical_tests_total",
                "description": "Deterministic PyAV/FFmpeg technical container tests",
            },
            "cinema_ci_validation_failures_total": {
                "value": validation_failures,
                "promql": "cinema_ci_validation_failures_total",
                "description": "Quality gate validation rejections",
            },
            "cinema_ci_repairs_total": {
                "value": repairs_total,
                "promql": "cinema_ci_repairs_total",
                "description": "Autonomous ADK repair attempts triggered via Grafana alert",
            },
            "cinema_ci_repair_success_total": {
                "value": repairs_success,
                "promql": "cinema_ci_repair_success_total",
                "description": "Successful autonomous repairs promoted to passing builds",
            },
        },
        "recent_logs": get_recent_logs(limit=25),
    }


def flush_telemetry() -> None:
    """Flush pending OpenTelemetry spans, metrics, and logs before worker exit."""
    global _tracer_provider
    if _tracer_provider:
        try:
            _tracer_provider.force_flush(timeout_millis=5000)
        except Exception:
            pass

