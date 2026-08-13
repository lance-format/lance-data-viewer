#!/bin/bash
set -Eeuo pipefail

if [ -n "${DATA_PATH:-}" ]; then
    if [ ! -d "$DATA_PATH" ]; then
        echo "ERROR: Data path $DATA_PATH does not exist or is not mounted"
        exit 1
    fi

    if [ ! -r "$DATA_PATH" ]; then
        echo "ERROR: Data path $DATA_PATH is not readable"
        exit 1
    fi
fi

PORT="${PORT:-8080}"

echo "Starting Lance Viewer on port ${PORT}..."
echo "Data path: ${DATA_PATH:-select in the web UI}"

exec python -m uvicorn app:app --host 0.0.0.0 --port "${PORT}"