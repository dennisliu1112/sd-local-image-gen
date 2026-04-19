#!/bin/bash
# Start the SD API server (foreground)
PORT=${1:-8080}
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "Installing dependencies..."
pip install -q -r requirements_api.txt

echo ""
echo "Starting SD API server on http://localhost:$PORT"
echo "Docs: http://localhost:$PORT/docs"
echo "Press Ctrl+C to stop."
echo ""

SD_API_PORT=$PORT python sd_api.py
