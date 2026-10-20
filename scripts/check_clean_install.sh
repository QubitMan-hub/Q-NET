#!/usr/bin/env bash
# Install the workbench into a fresh virtual environment and check that it works:
# test suite, headless run, server + UI + API.   Usage: scripts/check_clean_install.sh [workdir]
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
WORK="${1:-$(mktemp -d)}"
PORT="${QPV_PORT:-8799}"
echo "== fresh venv in $WORK"
python3 -m venv "$WORK/venv"
. "$WORK/venv/bin/activate"
pip install -q --upgrade pip
pip install -q "$REPO[server,test]"            # non-editable install: uses the packaged UI bundle
cd "$WORK"
echo "== installed: $(python -c 'import qpvsim; print(qpvsim.__version__, qpvsim.__file__)')"
echo "== test suite"
python -m pytest -q -p no:cacheprovider "$REPO/tests" -o addopts="" --rootdir "$REPO" | tail -2
echo "== headless run"
qpv run qpv_bb84_teleportation_attack --quiet
echo "== server"
qpv serve --port "$PORT" > "$WORK/serve.log" 2>&1 &
SRV=$!
trap 'kill $SRV 2>/dev/null || true' EXIT
for _ in $(seq 50); do curl -sf "http://127.0.0.1:$PORT/api/meta" >/dev/null && break; sleep 0.2; done
curl -sf "http://127.0.0.1:$PORT/" | grep -q '<div id="root">' && echo "UI bundle served"
curl -sf -X POST "http://127.0.0.1:$PORT/api/sim/run" -H 'Content-Type: application/json' -d '{}' \
  | python -c 'import json,sys; s=json.load(sys.stdin); print("API run:", s["decision"]["summary"]); assert s["stopped"]'
echo "== clean install OK"
