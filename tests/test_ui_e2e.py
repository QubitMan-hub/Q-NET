"""Browser end-to-end tests: the UI shows exactly what the engine reports.

Starts ``qpv serve`` on a free port and runs the Playwright scripts in
frontend/e2e/.  Skipped when Node.js, Playwright or the built UI bundle is
unavailable (e.g. a Python-only install).
"""

import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
E2E = ROOT / "frontend" / "e2e"
STATIC = ROOT / "src" / "qpvsim" / "server" / "static" / "index.html"


def _playwright_available() -> bool:
    if not shutil.which("node"):
        return False
    probe = "const r=require('module').createRequire(process.cwd()+'/');" \
            "for(const p of ['playwright','/opt/node22/lib/node_modules/playwright']){try{r(p);process.exit(0)}catch{}}process.exit(1)"
    return subprocess.run(["node", "-e", probe], cwd=ROOT / "frontend", capture_output=True).returncode == 0


pytestmark = pytest.mark.skipif(not (STATIC.exists() and _playwright_available()),
                                reason="needs node + playwright and a built UI bundle")


@pytest.fixture(scope="module")
def server():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen([sys.executable, "-m", "qpvsim.cli", "serve", "--port", str(port)],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            urllib.request.urlopen(url + "/api/meta", timeout=1)
            break
        except OSError:
            time.sleep(0.1)
    else:
        proc.kill()
        pytest.fail("server did not start")
    yield url
    proc.terminate()
    proc.wait(timeout=10)


@pytest.mark.parametrize("script", ["run.mjs", "build.mjs"])
def test_browser_scenario(server, script, tmp_path):
    r = subprocess.run(["node", str(E2E / script), server, str(tmp_path)], cwd=ROOT / "frontend",
                       capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
