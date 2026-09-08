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
echo "🎬 Cinema CI: Starting in MOCK MODE (Offline Rehearsal)"
echo "========================================================"
echo "• AI Reasoning:  Offline Deterministic Parser"
echo "• Video Gen:     Instant Local Fixtures (fixtures/)"
echo "• Observability: Local Telemetry Mirror"
echo "• Server URL:    http://localhost:8080"
echo "• Cost/Billing:  \$0.00 (Zero External API calls)"
echo "========================================================"

# Activate virtual environment if present
if [ -f "$ROOT_DIR/.venv/bin/activate" ]; then
    source "$ROOT_DIR/.venv/bin/activate"
fi
export PATH="$ROOT_DIR/.venv/bin:$PATH"

export MOCK_MODE=true
export STRICT_MODE=false
export GENERATOR_TYPE=fixture

exec uvicorn app.main:app --host 0.0.0.0 --port 8080 --app-dir "$ROOT_DIR" --reload
