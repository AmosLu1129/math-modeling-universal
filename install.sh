#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY_BIN="${PYTHON:-$(command -v python3 || command -v python)}"
exec "$PY_BIN" "$SCRIPT_DIR/install.py" "$@"
