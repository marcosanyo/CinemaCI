"""Cinema CI — Official Grafana MCP Subprocess Client.

Launches and communicates with the official Grafana MCP Server (`mcp-grafana`)
via `uvx mcp-grafana` over standard I/O (STDIO) transport.
Enforces Strict Mode: No silent fallbacks when STRICT_MODE=true or CINEMA_STRICT_MODE=1.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import time
from typing import Any

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class OfficialGrafanaMcpProcess:
    """Manages the official `mcp-grafana` subprocess over STDIO."""

    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self._req_id = 0
        self._lock = threading.RLock()
        self._initialized = False
        self._tools_cache: list[dict[str, Any]] = []

    def start(self) -> bool:
        """Start the official mcp-grafana server via uvx."""
        with self._lock:
            if self.proc and self.proc.poll() is None:
                return True

            # Find mcp-grafana command
            cmd = None
            if shutil.which("mcp-grafana"):
                cmd = [shutil.which("mcp-grafana")]
            elif os.path.exists("/root/.local/bin/mcp-grafana"):
                cmd = ["/root/.local/bin/mcp-grafana"]
            elif os.path.exists(os.path.expanduser("~/.local/bin/mcp-grafana")):
                cmd = [os.path.expanduser("~/.local/bin/mcp-grafana")]
            else:
                venv_uvx = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.venv/bin/uvx"))
                if os.path.exists(venv_uvx):
                    cmd = [venv_uvx, "--python", "3.12", "mcp-grafana"]
                elif shutil.which("uvx"):
                    cmd = [shutil.which("uvx"), "--python", "3.12", "mcp-grafana"]
                elif shutil.which("uv"):
                    cmd = [shutil.which("uv"), "tool", "run", "--python", "3.12", "mcp-grafana"]

            if not cmd:
                logger.warning("mcp-grafana or uvx binary not found; official mcp-grafana subprocess cannot be started.")
                return False

            env = os.environ.copy()
            env["PATH"] = f"/root/.local/bin:{os.path.expanduser('~/.local/bin')}:{env.get('PATH', '')}"
            # Pass Grafana Cloud connection details
            grafana_url = env.get("GRAFANA_URL", "https://friendlysherbet668.grafana.net")
            grafana_token = env.get("GRAFANA_SA_TOKEN", "")
            env["GRAFANA_URL"] = grafana_url
            if grafana_token:
                env["GRAFANA_SERVICE_ACCOUNT_TOKEN"] = grafana_token
                env["GRAFANA_AUTH"] = f"Bearer {grafana_token}"
                env["GRAFANA_API_KEY"] = grafana_token
                env["GRAFANA_TOKEN"] = grafana_token

            try:
                logger.info(f"Launching official mcp-grafana server via: {' '.join(cmd)}")
                self.proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    env=env,
                )

                # Send MCP initialize
                self._req_id += 1
                init_req = {
                    "jsonrpc": "2.0",
                    "id": self._req_id,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "cinema-ci-adk", "version": "1.0.0"},
                    },
                }
                self.proc.stdin.write(json.dumps(init_req) + "\n")
                self.proc.stdin.flush()

                init_res_line = self.proc.stdout.readline()
                if not init_res_line:
                    logger.warning("No response from mcp-grafana process during initialize.")
                    return False

                init_data = json.loads(init_res_line)
                server_info = init_data.get("result", {}).get("serverInfo", {})
                logger.info(f"Official Grafana MCP Server initialized: {server_info}")

                # Send initialized notification
                self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
                self.proc.stdin.flush()

                # Fetch available tools
                self._req_id += 1
                self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self._req_id, "method": "tools/list", "params": {}}) + "\n")
                self.proc.stdin.flush()

                tools_line = self.proc.stdout.readline()
                if tools_line:
                    tools_data = json.loads(tools_line)
                    self._tools_cache = tools_data.get("result", {}).get("tools", [])
                    logger.info(f"Discovered {len(self._tools_cache)} official tools from mcp-grafana server.")

                self._initialized = True
                return True

            except Exception as e:
                logger.warning(f"Failed to launch official mcp-grafana server: {e}")
                self.proc = None
                return False

    def stop(self) -> None:
        """Stop running mcp-grafana process."""
        with self._lock:
            if self.proc:
                try:
                    self.proc.terminate()
                    self.proc.wait(timeout=2)
                except Exception:
                    try:
                        self.proc.kill()
                    except Exception:
                        pass
                self.proc = None
            self._initialized = False
            self._tools_cache = []

    def restart(self) -> bool:
        """Restart mcp-grafana process with current environment variables."""
        self.stop()
        return self.start()

    def get_tool_names(self) -> list[str]:
        """Return list of all discovered MCP tool names."""
        with self._lock:
            if not self._initialized:
                self.start()
            return [t.get("name", "") for t in self._tools_cache if "name" in t]

    def has_tool(self, tool_name: str) -> bool:
        """Check if a tool exists in discovered MCP tools."""
        return tool_name in self.get_tool_names()

    def call_mcp_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
        """Call a tool on the official mcp-grafana subprocess via JSON-RPC 2.0."""
        with self._lock:
            if not self._initialized:
                if not self.start():
                    return None

            try:
                self._req_id += 1
                req = {
                    "jsonrpc": "2.0",
                    "id": self._req_id,
                    "method": "tools/call",
                    "params": {
                        "name": name,
                        "arguments": arguments,
                    },
                }
                logger.info(f"[Official:mcp-grafana] --> STDIO Request: tools/call tool={name}")
                self.proc.stdin.write(json.dumps(req) + "\n")
                self.proc.stdin.flush()

                line = self.proc.stdout.readline()
                if not line:
                    return None

                resp = json.loads(line)
                logger.info(f"[Official:mcp-grafana] <-- STDIO Response: id={resp.get('id')}")

                if "result" in resp:
                    content = resp["result"].get("content", [])
                    if content and isinstance(content, list):
                        text = content[0].get("text", "{}")
                        try:
                            data = json.loads(text)
                            if isinstance(data, dict):
                                data["source"] = "official-mcp-grafana"
                                data["is_real_mcp"] = True
                                data["tool_name"] = name
                                return data
                            else:
                                return {
                                    "result": data,
                                    "raw_text": text,
                                    "source": "official-mcp-grafana",
                                    "is_real_mcp": True,
                                    "tool_name": name,
                                }
                        except Exception:
                            return {
                                "text": text,
                                "source": "official-mcp-grafana",
                                "is_real_mcp": True,
                                "tool_name": name,
                            }
                    return {"result": resp["result"], "source": "official-mcp-grafana", "is_real_mcp": True, "tool_name": name}
                elif "error" in resp:
                    return {"error": resp["error"], "source": "official-mcp-grafana", "is_real_mcp": True, "tool_name": name}

            except Exception as e:
                logger.warning(f"Error communicating with mcp-grafana subprocess: {e}")
                return None


# Global process manager
_mcp_process = OfficialGrafanaMcpProcess()


class GrafanaMcpClient:
    """Client for Grafana MCP tools.
    Prioritizes official `uvx mcp-grafana` subprocess.
    Enforces Strict Mode: raises RuntimeError on failure when STRICT_MODE=true.
    """

    def __init__(self):
        self.official_proc = _mcp_process
        self.fallbacks_used_count = 0

    def reset_fallback_counter(self) -> None:
        """Reset the fallback invocation counter."""
        self.fallbacks_used_count = 0

    def get_fallback_count(self) -> int:
        """Return the number of times fallback was invoked."""
        return self.fallbacks_used_count

    def is_strict_mode(self) -> bool:
        """Check if Strict Mode is enforced (default True for submission integrity)."""
        mock_mode = os.environ.get("MOCK_MODE", "false").lower() in ("true", "1", "yes")
        if mock_mode:
            return False
        val = os.environ.get("STRICT_MODE", "true").lower()
        cinema_strict = os.environ.get("CINEMA_STRICT_MODE", "1").lower()
        return val in ("true", "1", "yes") or cinema_strict in ("true", "1", "yes")

    def is_mcp_connected(self) -> bool:
        """Check if official mcp-grafana subprocess is running."""
        return bool(self.official_proc._initialized and self.official_proc.proc and self.official_proc.proc.poll() is None)

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Invoke an MCP tool using official mcp-grafana tool names and schema."""
        prom_uid = os.environ.get("PROM_DATASOURCE_UID", "grafanacloud-prom")
        loki_uid = os.environ.get("LOKI_DATASOURCE_UID", "grafanacloud-logs")
        tempo_uid = os.environ.get("TEMPO_DATASOURCE_UID", "grafanacloud-traces")

        discovered_tools = self.official_proc.get_tool_names()
        official_name = tool_name
        official_args = dict(arguments)

        # 1. Prometheus Mapping
        if tool_name in ("grafana_prometheus_query", "prometheus_query", "query_prometheus"):
            official_name = "query_prometheus"
            query_expr = arguments.get("query") or arguments.get("expr", "cinema_ci_active_regressions")
            official_args = {
                "datasourceUid": arguments.get("datasourceUid", prom_uid),
                "expr": query_expr,
                "endTime": arguments.get("endTime", "now"),
                "queryType": "instant",
            }

        # 2. Loki Mapping
        elif tool_name in ("grafana_loki_query", "loki_query", "query_loki_logs"):
            official_name = "query_loki_logs"
            logql_expr = arguments.get("query") or arguments.get("logql", '{service_name="cinema-ci"}')
            official_args = {
                "datasourceUid": arguments.get("datasourceUid", loki_uid),
                "logql": logql_expr,
                "limit": arguments.get("limit", 20),
            }

        # 3. Tempo Traces Mapping (Dynamic Discovery of Tempo Proxied Tools / API)
        elif (
            tool_name in ("grafana_tempo_query", "query_tempo_traces", "tempo_query", "get_trace", "query_tempo", "get_baseline_build_trace", "tempo_get-trace", "tempo_get_trace")
            or tool_name.startswith("tempo_")
        ):
            trace_id = arguments.get("trace_id") or arguments.get("traceId") or arguments.get("query", "")
            
            # Check for proxied tempo tools from tools/list
            tempo_proxied = [t for t in discovered_tools if t.startswith("tempo_")]
            if tempo_proxied:
                # Prefer exact match or query tool
                if "tempo_get-trace" in tempo_proxied and trace_id:
                    official_name = "tempo_get-trace"
                    official_args = {
                        "datasourceUid": arguments.get("datasourceUid", tempo_uid),
                        "trace_id": trace_id,
                        "traceId": trace_id,
                    }
                elif "tempo_get_trace" in tempo_proxied and trace_id:
                    official_name = "tempo_get_trace"
                    official_args = {
                        "datasourceUid": arguments.get("datasourceUid", tempo_uid),
                        "trace_id": trace_id,
                        "traceId": trace_id,
                    }
                elif "tempo_query" in tempo_proxied:
                    official_name = "tempo_query"
                    official_args = {
                        "datasourceUid": arguments.get("datasourceUid", tempo_uid),
                        "query": trace_id or '{.service.name="cinema-ci"}',
                    }
                else:
                    official_name = tempo_proxied[0]
                    official_args = {
                        "datasourceUid": arguments.get("datasourceUid", tempo_uid),
                        "trace_id": trace_id,
                    } if trace_id else arguments
            elif "grafana_api_request" in discovered_tools:
                # Fallback to official grafana_api_request tool via datasource proxy
                official_name = "grafana_api_request"
                official_args = {
                    "endpoint": f"/api/datasources/proxy/uid/{tempo_uid}/api/traces/{trace_id}" if trace_id else f"/api/datasources/proxy/uid/{tempo_uid}/api/search",
                    "method": "GET",
                }
            else:
                official_name = "query_tempo_traces"
                official_args = {
                    "datasourceUid": arguments.get("datasourceUid", tempo_uid),
                    "query": trace_id or '{.service.name="cinema-ci"}',
                    "limit": arguments.get("limit", 10),
                }

        # 4. Alerting Mapping
        elif tool_name in ("grafana_get_alerts", "alerting_list_rules", "alerting_manage_rules"):
            if "alerting_manage_rules" in discovered_tools:
                official_name = "alerting_manage_rules"
                official_args = {
                    "operation": "list",
                    "states": ["firing"],
                }
            else:
                official_name = "alerting_manage_rules"
                official_args = dict(arguments)

        # 1. Execute on official mcp-grafana subprocess
        result = self.official_proc.call_mcp_tool(official_name, official_args)
        is_failing_result = (
            result is None
            or "error" in result
            or "connection refused" in str(result).lower()
            or "unauthorized" in str(result).lower()
            or "failed to" in str(result).lower()
            or (isinstance(result, dict) and result.get("status") == "error")
        )

        if result is not None and not is_failing_result:
            return result

        # Strict Enforcement: Fallback is strictly forbidden outside MOCK_MODE
        mock_mode = os.environ.get("MOCK_MODE", "false").lower() in ("true", "1", "yes")
        if not mock_mode:
            err_msg = (
                f"PRODUCTION / STRICT INTEGRITY VIOLATION: Official Grafana MCP tool '{official_name}' failed "
                f"or endpoint was unreachable (details: {result}). "
                f"Silent fallback and fake responses are strictly prohibited outside MOCK_MODE."
            )
            logger.error(err_msg)
            raise RuntimeError(err_msg)

        # Explicit fallback only when MOCK_MODE is enabled
        self.fallbacks_used_count += 1
        logger.info(f"MOCK_MODE active: Using offline local telemetry for '{official_name}'.")
        return self._local_telemetry_fallback(tool_name, arguments)

    def _local_telemetry_fallback(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Explicit local fallback for offline development ONLY when STRICT_MODE=false."""
        from app.engine import get_all_builds, get_build
        builds = get_all_builds()

        if tool_name in ("grafana_prometheus_query", "prometheus_query", "query_prometheus"):
            query = arguments.get("query", "")
            regressions = sum(b.regressions for b in builds if b.status.value == "BLOCKED")
            total_tests = sum(b.tests_total for b in builds)
            passed_tests = sum(b.tests_passed for b in builds)

            metrics_map = {
                "cinema_ci_active_regressions": regressions,
                "cinema_ci_test_pass_ratio": (passed_tests / total_tests) if total_tests else 1.0,
                "cinema_ci_release_ready": 1 if any(b.release_ready for b in builds) else 0,
                "cinema_ci_builds_total": len(builds),
            }
            val = metrics_map.get(query, 0)
            return {
                "status": "success",
                "data": {
                    "resultType": "vector",
                    "result": [{"metric": {"__name__": query, "job": "cinema-ci"}, "value": [time.time(), str(val)]}],
                },
                "source": "local-fallback",
                "is_real_mcp": False,
                "fallbacks_used": self.fallbacks_used_count,
            }

        elif tool_name in ("grafana_loki_query", "loki_query", "query_loki_logs"):
            logs = []
            for b in builds:
                for t in b.test_results:
                    if t.status.value in ("REGRESSION", "FAIL"):
                        logs.append({
                            "timestamp": b.created_at,
                            "event": "cinema_test_result",
                            "build_id": b.build_id,
                            "shot_id": t.scope,
                            "test_id": t.test_id,
                            "status": t.status.value,
                            "expected": t.expected,
                            "observed": t.observed,
                        })
            return {
                "status": "success",
                "data": {"resultType": "streams", "result": [{"stream": {"service_name": "cinema-ci"}, "values": [[l["timestamp"], json.dumps(l)] for l in logs]}]},
                "source": "local-fallback",
                "is_real_mcp": False,
                "fallbacks_used": self.fallbacks_used_count,
            }

        elif tool_name in ("grafana_get_alerts", "alerting_list_rules", "alerting_manage_rules"):
            alerts = []
            for b in builds:
                if b.status.value == "BLOCKED" and (b.regressions > 0 or b.tests_passed < b.tests_total):
                    alerts.append({
                        "labels": {"alertname": "CinemaRegressionDetected", "severity": "critical", "build_id": b.build_id, "project_id": b.project_id},
                        "annotations": {"summary": f"Active regression in {b.build_id}"},
                        "state": "firing",
                    })
            return {
                "status": "success",
                "data": {"alerts": alerts},
                "source": "local-fallback",
                "is_real_mcp": False,
                "fallbacks_used": self.fallbacks_used_count,
            }

        elif tool_name in ("grafana_tempo_query", "query_tempo_traces", "tempo_query", "get_trace", "query_tempo", "get_baseline_build_trace"):
            req_build_id = arguments.get("build_id") or arguments.get("traceId")
            target_build = get_build(req_build_id) if req_build_id else (builds[0] if builds else None)
            trace_id = target_build.trace_id if target_build and target_build.trace_id else "4bf92f3577b34da6a3ce929d0e0e4736"
            build_id = target_build.build_id if target_build else (req_build_id or "build_0016")

            trace_payload = {
                "trace_id": trace_id,
                "spans": [
                    {
                        "name": "cinema.build",
                        "span_id": "0000000000000001",
                        "attributes": {
                            "cinema.project_id": "cafe-envelope",
                            "cinema.build_id": build_id,
                        },
                    },
                    {
                        "name": "cinema.generate.shot",
                        "span_id": "0000000000000003",
                        "parent_span_id": "0000000000000001",
                        "attributes": {
                            "cinema.shot_id": "shot_01",
                            "cinema.generator": "VeoGenerator",
                            "cinema.model": "veo-3.1-lite-generate-001",
                            "cinema.output.artifact_id": "shot_01:v1",
                            "cinema.output.sha256": "76d9295d4e12fa89",
                        },
                    },
                    {
                        "name": "cinema.generate.shot",
                        "span_id": "0000000000000004",
                        "parent_span_id": "0000000000000001",
                        "attributes": {
                            "cinema.shot_id": "shot_02",
                            "cinema.generator": "VeoGenerator",
                            "cinema.model": "veo-3.1-lite-generate-001",
                            "cinema.output.artifact_id": "shot_02:v1",
                            "cinema.output.sha256": "3a88c4b12df098ae",
                        },
                    },
                    {
                        "name": "cinema.generate.shot",
                        "span_id": "0000000000000005",
                        "parent_span_id": "0000000000000001",
                        "attributes": {
                            "cinema.shot_id": "shot_03",
                            "cinema.generator": "VeoGenerator",
                            "cinema.model": "veo-3.1-lite-generate-001",
                            "cinema.output.artifact_id": "shot_03:v1",
                            "cinema.output.sha256": "81fca992bc410291",
                        },
                    },
                    {
                        "name": "cinema.reference.select",
                        "span_id": "0000000000000006",
                        "parent_span_id": "0000000000000001",
                        "attributes": {
                            "cinema.consumer": "poster:v1",
                            "cinema.reference.candidates": "shot_01:keyframe:v1, shot_02:keyframe:v1, shot_03:keyframe:v1",
                            "cinema.reference.selected": "shot_01:keyframe:v1",
                            "cinema.selection.reason": "runtime_visual_composition_gemini_selection",
                        },
                    },
                    {
                        "name": "cinema.generate.poster",
                        "span_id": "0000000000000007",
                        "parent_span_id": "0000000000000001",
                        "attributes": {
                            "cinema.artifact_id": "poster",
                            "cinema.input.selected_reference": "shot_01:keyframe:v1",
                            "cinema.output.artifact_id": "poster:v1",
                            "cinema.output.sha256": "f901ab8872cd43e1",
                        },
                    },
                ],
            }
            return {
                "status": "success",
                "data": trace_payload,
                "trace": trace_payload,
                "source": "local-fallback",
                "is_real_mcp": False,
                "fallbacks_used": self.fallbacks_used_count,
            }

        return {
            "error": f"Tool '{tool_name}' not implemented in fallback",
            "source": "local-fallback",
            "is_real_mcp": False,
            "fallbacks_used": self.fallbacks_used_count,
        }


# Singleton instance
mcp_client = GrafanaMcpClient()

