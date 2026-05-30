#!/bin/bash
# Start the SD API server (foreground)
PORT=${1:-8080}
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# Use local venv if available
if [ -f "$ROOT/.venv/bin/python" ]; then
    PYTHON="$ROOT/.venv/bin/python"
else
    PYTHON="$(which python3)"
fi

echo "Python: $PYTHON"
echo ""
echo "Starting SD API server on http://localhost:$PORT"
echo "Docs: http://localhost:$PORT/docs"
echo "Press Ctrl+C to stop."
echo ""

SD_API_PORT=$PORT "$PYTHON" sd_api.py
