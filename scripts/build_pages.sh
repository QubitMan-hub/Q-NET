#!/usr/bin/env bash
# Build the static, server-less workbench for GitHub Pages into ./site (or $1).
# The UI talks to the Python engine running in the browser via Pyodide.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$(mkdir -p "${1:-$REPO/site}" && cd "${1:-$REPO/site}" && pwd)"
cd "$REPO/frontend"
[ -d node_modules ] || npm ci --no-audit --no-fund
VITE_BACKEND=pyodide npx vite build --base ./ --outDir "$OUT" --emptyOutDir
cd "$REPO"
python3 - "$OUT/qpvsim.zip" <<'PY'
import sys, zipfile, pathlib
out = sys.argv[1]
root = pathlib.Path("src")
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for p in sorted((root / "qpvsim").rglob("*")):
        rel = p.relative_to(root)
        if p.is_dir() or "__pycache__" in rel.parts or "static" in rel.parts:
            continue
        z.write(p, rel.as_posix())
print("engine package:", out, pathlib.Path(out).stat().st_size // 1024, "KiB")
PY
touch "$OUT/.nojekyll"
echo "static site ready in $OUT"
