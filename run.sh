#!/usr/bin/env bash
# One step to run the QPV Workbench locally: installs what is missing, builds the interface if needed,
# starts the server and opens your browser.
#   ./run.sh                     the workbench with the start screen
#   ./run.sh b7_two_photons      straight into one scenario (list them with: qpv scenarios)
set -euo pipefail
cd "$(dirname "$0")"

PY=${PYTHON:-python3}
if ! command -v qpv >/dev/null 2>&1 || ! $PY -c "import fastapi, uvicorn, qpvsim" >/dev/null 2>&1; then
  echo "Installing the simulator (Python)..."
  $PY -m pip install --quiet -e ".[server]"
fi

if [ ! -f src/qpvsim/server/static/index.html ]; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "The web interface needs to be built once, which needs Node.js 18+ (https://nodejs.org)." >&2
    exit 1
  fi
  echo "Building the web interface (first run only)..."
  (cd frontend && npm install --silent && npm run build --silent)
fi

if [ $# -gt 0 ]; then
  exec qpv serve --open --scenario "$1"
else
  exec qpv serve --open
fi
