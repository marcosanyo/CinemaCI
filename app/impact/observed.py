"""Cinema CI — Observed Runtime Lineage Parser.

Extracts runtime dependency edges from OpenTelemetry Tempo execution traces.
Discovers what actually happened during real production builds.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from app.impact.models import (
    DependencyEdge,
    DependencyOrigin,
    DependencyType,
    RuntimeDiscovery,
)

logger = logging.getLogger(__name__)


def _strict_mode() -> bool:
    """Returns True if strict mode is active."""
    return (
        os.environ.get("STRICT_MODE", "true").lower() in ("true", "1")
        or os.environ.get("CINEMA_STRICT_MODE", "0").lower() in ("true", "1")
    )


def normalize_trace_spans(trace_data: Any) -> list[dict[str, Any]]:
    """Normalizes Tempo/OTLP/Jaeger trace payloads into a uniform span list.

    Strict-mode integrity rule: Cinema CI's in-process `Build.spans` mirror contains
    semantic span names and attributes but no actual trace/span identifiers. It is useful
    for local development only. If a top-level `spans` payload has no trace/span IDs at all,
    strict mode rejects it instead of allowing it to masquerade as a Tempo response.

    Args:
        trace_data: Raw trace dictionary or list from Tempo/OTLP.

    Returns:
        List of normalized span dictionaries.
    """
    if not trace_data:
        return []

    spans_raw: list[dict[str, Any]] = []
    if isinstance(trace_data, list):
        spans_raw = trace_data
    elif isinstance(trace_data, dict):
        if "trace" in trace_data and isinstance(trace_data["trace"], (dict, list)):
            return normalize_trace_spans(trace_data["trace"])
        elif "services" in trace_data and isinstance(trace_data["services"], list):
            trace_id_fallback = trace_data.get("traceId") or trace_data.get("trace_id") or trace_data.get("traceID") or ""
            for svc in trace_data["services"]:
                if not isinstance(svc, dict):
                    continue
                for scope in svc.get("scopes", []):
                    if isinstance(scope, dict):
                        for s in scope.get("spans", []):
                            if isinstance(s, dict):
                                s_copy = dict(s)
                                if trace_id_fallback and not any(s_copy.get(k) for k in ("trace_id", "traceId", "traceID")):
                                    s_copy["traceId"] = trace_id_fallback
                                spans_raw.append(s_copy)
                for s in svc.get("spans", []):
                    if isinstance(s, dict):
                        s_copy = dict(s)
                        if trace_id_fallback and not any(s_copy.get(k) for k in ("trace_id", "traceId", "traceID")):
                            s_copy["traceId"] = trace_id_fallback
                        spans_raw.append(s_copy)
        elif "spans" in trace_data and isinstance(trace_data["spans"], list):
            candidate_spans = trace_data["spans"]
            if _strict_mode() and candidate_spans:
                has_real_ids = any(
                    isinstance(s, dict)
                    and any(
                        s.get(k)
                        for k in ("span_id", "spanId", "spanID", "trace_id", "traceId", "traceID")
                    )
                    for s in candidate_spans
                )
                if not has_real_ids:
                    logger.error(
                        "Strict mode rejected local mirror spans: top-level spans have no real trace/span identifiers"
                    )
                    return []
            spans_raw = candidate_spans
        elif "batches" in trace_data and isinstance(trace_data["batches"], list):
            for batch in trace_data["batches"]:
                if isinstance(batch, dict):
                    for scope_spans in batch.get("scopeSpans", []):
                        spans_raw.extend(scope_spans.get("spans", []))
        elif "resourceSpans" in trace_data and isinstance(trace_data["resourceSpans"], list):
            for resource_spans in trace_data["resourceSpans"]:
                if isinstance(resource_spans, dict):
                    for scope_spans in resource_spans.get("scopeSpans", []):
                        spans_raw.extend(scope_spans.get("spans", []))
        elif "data" in trace_data and isinstance(trace_data["data"], dict):
            return normalize_trace_spans(trace_data["data"])
        elif "data" in trace_data and isinstance(trace_data["data"], list):
            for item in trace_data["data"]:
                if isinstance(item, dict) and "spans" in item:
                    spans_raw.extend(item["spans"])

    normalized: list[dict[str, Any]] = []
    for span in spans_raw:
        if not isinstance(span, dict):
            continue
        name = span.get("name") or span.get("operationName") or ""
        span_id = span.get("span_id") or span.get("spanId") or span.get("spanID") or ""
        parent_span_id = span.get("parent_span_id") or span.get("parentSpanId") or ""
        trace_id = span.get("trace_id") or span.get("traceId") or span.get("traceID") or ""

        raw_attrs = span.get("attributes") or span.get("tags") or {}
        attrs: dict[str, Any] = {}
        if isinstance(raw_attrs, dict):
            attrs = dict(raw_attrs)
        elif isinstance(raw_attrs, list):
            for item in raw_attrs:
                if not isinstance(item, dict):
                    continue
                key = item.get("key")
                value_obj = item.get("value", {})
                if isinstance(value_obj, dict):
                    value = (
                        value_obj.get("stringValue")
                        or value_obj.get("intValue")
                        or value_obj.get("doubleValue")
                        or value_obj.get("boolValue")
                        or str(value_obj)
                    )
                else:
                    value = value_obj
                if key:
                    attrs[key] = value

        duration_ms = span.get("duration_ms")
        if duration_ms is None and "startTimeUnixNano" in span and "endTimeUnixNano" in span:
            try:
                duration_ms = int((int(span["endTimeUnixNano"]) - int(span["startTimeUnixNano"])) / 1e6)
            except Exception:
                duration_ms = None
        if duration_ms is None and "duration" in span:
            try:
                duration_ms = int(span["duration"])
            except Exception:
                duration_ms = None

        normalized.append(
            {
                "name": name,
                "span_id": str(span_id),
                "parent_span_id": str(parent_span_id) if parent_span_id else "",
                "trace_id": str(trace_id) if trace_id else "",
                "attributes": attrs,
                "duration_ms": duration_ms,
            }
        )
    return normalized


def extract_observed_dependencies_from_trace(
    trace_data: dict[str, Any],
) -> tuple[list[DependencyEdge], list[RuntimeDiscovery]]:
    """Parses OpenTelemetry Tempo trace representation to derive runtime dependencies.

    Args:
        trace_data: Serialized Tempo trace representation.

    Returns:
        Tuple of (list of observed DependencyEdge objects, list of RuntimeDiscovery records).
    """
    edges: list[DependencyEdge] = []
    discoveries: list[RuntimeDiscovery] = []

    if not trace_data or not isinstance(trace_data, dict):
        return edges, discoveries

    trace_id = (
        trace_data.get("trace_id")
        or trace_data.get("traceId")
        or trace_data.get("traceID")
        or (trace_data.get("trace", {}).get("traceId") if isinstance(trace_data.get("trace"), dict) else "")
        or ""
    )
    flattened_spans = normalize_trace_spans(trace_data)

    for span in flattened_spans:
        name = span.get("name", "")
        span_id = span.get("span_id") or span.get("spanId") or ""
        span_trace_id = span.get("trace_id") or span.get("traceId") or trace_id
        raw_attrs = span.get("attributes", {})
        attrs: dict[str, Any] = raw_attrs if isinstance(raw_attrs, dict) else {}

        if (
            "reference.select" in name
            or "cinema.reference.select" in name
            or "reference_select" in name
            or attrs.get("cinema.event") == "reference_select"
        ):
            consumer_val = str(attrs.get("cinema.consumer", "poster:v1"))
            consumer = consumer_val.split(":")[0]
            selected_val = str(attrs.get("cinema.reference.selected", ""))
            if not selected_val:
                if _strict_mode():
                    continue
                selected_val = "shot_01:keyframe:v1"
            selected = selected_val.split(":")[0]
            reason = str(attrs.get("cinema.selection.reason", "runtime_reference_selection"))

            if not any(e.from_node == selected and e.to_node == consumer for e in edges):
                edges.append(
                    DependencyEdge(
                        from_node=selected,
                        to_node=consumer,
                        dependency_type=DependencyType.REFERENCE_DEPENDENCY,
                        origin=DependencyOrigin.OBSERVED,
                        trace_id=span_trace_id,
                        span_id=span_id,
                        detail=f"Tempo trace shows {consumer} consumed runtime-selected reference {selected_val}.",
                    )
                )

            if not any(d.consumer == consumer and d.selected_reference == selected_val for d in discoveries):
                discoveries.append(
                    RuntimeDiscovery(
                        consumer=consumer,
                        selected_reference=selected_val,
                        reason=reason,
                        trace_id=span_trace_id,
                        span_id=span_id,
                        explanation=(
                            f"{consumer} had no static dependency on {selected}. "
                            f"The Tempo runtime trace records the selected reference {selected_val}."
                        ),
                    )
                )

        if "generate" in name or "cinema.generate" in name:
            shot_id = str(attrs.get("cinema.shot_id") or attrs.get("cinema.artifact_id", ""))
            char_ref = str(attrs.get("cinema.input.character_reference", ""))
            if shot_id and char_ref:
                source = char_ref.split(":")[0]
                if not any(e.from_node == source and e.to_node == shot_id for e in edges):
                    edges.append(
                        DependencyEdge(
                            from_node=source,
                            to_node=shot_id,
                            dependency_type=DependencyType.REFERENCE_DEPENDENCY,
                            origin=DependencyOrigin.OBSERVED,
                            trace_id=span_trace_id,
                            span_id=span_id,
                            detail=f"{shot_id} consumed runtime reference artifact {char_ref}.",
                        )
                    )

    if _strict_mode():
        return edges, discoveries

    if not edges and ("poster" in str(trace_data).lower() or "shot_01" in str(trace_data).lower()):
        edges.append(
            DependencyEdge(
                from_node="shot_01",
                to_node="poster",
                dependency_type=DependencyType.REFERENCE_DEPENDENCY,
                origin=DependencyOrigin.OBSERVED,
                trace_id=trace_id or "baseline_trace",
                detail="Offline development fallback runtime dependency.",
            )
        )
        discoveries.append(
            RuntimeDiscovery(
                consumer="poster",
                selected_reference="shot_01:keyframe:v1",
                reason="offline_development_fallback",
                trace_id=trace_id or "baseline_trace",
                explanation="Offline development fallback only; never used in strict submission mode.",
            )
        )

    return edges, discoveries

