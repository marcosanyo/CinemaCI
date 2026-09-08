"""Cinema CI — Grafana Alertmanager Webhook Handler.

Processes webhook notifications from Grafana Cloud Alertmanager and
triggers autonomous investigation and repair routines.
"""

from __future__ import annotations

from typing import Any
from app.agent import agent


async def handle_grafana_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    """Handles Grafana webhook alert payloads and triggers agent investigations.

    Args:
        payload: The JSON webhook payload from Grafana Alertmanager.

    Returns:
        Dictionary detailing investigation initiation status and steps executed.
    """
    alerts = payload.get("alerts", [])
    if not alerts:
        return {"status": "ignored", "reason": "No alerts found in payload"}

    investigation_results: list[dict[str, Any]] = []

    for alert in alerts:
        if alert.get("status") != "firing":
            continue

        labels = alert.get("labels", {})
        alert_name = labels.get("alertname", "Unknown Alert")

        steps = await agent.run_investigation(alert)
        investigation_results.append({
            "alert": alert_name,
            "steps_taken": len(steps),
        })

    if not investigation_results:
        return {"status": "ignored", "reason": "No firing alerts found"}

    return {
        "status": "investigation_started",
        "results": investigation_results,
    }

