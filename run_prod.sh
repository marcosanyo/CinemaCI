#!/usr/bin/env bash
set -e

# Resolve physical script location following symlinks
SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do
  DIR="$( cd -P "$( dirname "$SOURCE" )" >/dev/null 2>&1 && pwd )"
  SOURCE="$(readlink "$SOURCE")"
  [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
ROOT_DIR="$( cd -P "$( dirname "$SOURCE" )" >/dev/null 2>&1 && pwd )"

# Safety check: if ROOT_DIR is inside scripts, move up to repo root
if [ ! -f "$ROOT_DIR/cinema.yaml" ] && [ -f "$ROOT_DIR/../cinema.yaml" ]; then
    ROOT_DIR="$( cd -P "$ROOT_DIR/.." >/dev/null 2>&1 && pwd )"
fi

cd "$ROOT_DIR"
export PYTHONPATH="$ROOT_DIR:${PYTHONPATH:-}"

echo "========================================================"
echo "🚀 Cinema CI: Starting in PRODUCTION MODE (Strict Mode)"
echo "========================================================"
echo "• AI Model:      Vertex AI Gemini 3.8 Flash (Pinned)"
echo "• Video Gen:     Vertex AI Veo 3.1"
echo "• Agent MCP:     Official mcp-grafana (STDIO)"
echo "• Telemetry:     Grafana Cloud (Tempo, Loki, Prometheus)"
echo "• Server URL:    http://localhost:8080"
echo "• Strictness:    STRICT_MODE=true (Fail-Fast, Zero Fakes)"
echo "========================================================"

# Activate virtual environment if present
if [ -f "$ROOT_DIR/.venv/bin/activate" ]; then
    source "$ROOT_DIR/.venv/bin/activate"
fi
export PATH="$ROOT_DIR/.venv/bin:$PATH"

export MOCK_MODE=false
export STRICT_MODE=true
export GENERATOR_TYPE=veo

exec uvicorn app.main:app --host 0.0.0.0 --port 8080 --app-dir "$ROOT_DIR" --reload
