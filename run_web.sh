#!/usr/bin/env bash

set -euo pipefail

PORT="${1:-8000}"

echo "启动 DuReading V2: http://localhost:${PORT}"
python3 web_server.py --port "${PORT}"
