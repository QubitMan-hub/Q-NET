"""FastAPI bridge between the browser UI and a :class:`~qpvsim.session.Session`.

All routes are implemented once in :class:`qpvsim.webapi.WebAPI`; this module
only adapts HTTP requests to it and serves the built UI.  The same dispatcher
runs inside the browser (Pyodide) for the static GitHub Pages build.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..session import Session
from ..webapi import WebAPI

STATIC = Path(__file__).parent / "static"

DOWNLOADS = {
    "/api/project/export": "project.qpv.json",
    "/api/sim/export": "trace.qpvtrace.json",
}


def create_app(session: Optional[Session] = None) -> FastAPI:
    app = FastAPI(title="QPV Workbench", version=__version__)
    api = WebAPI(session or Session())

    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT"])
    async def dispatch(path: str, request: Request):
        raw = await request.body()
        try:
            body = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            return JSONResponse({"detail": "request body is not valid JSON"}, status_code=400)
        url = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        status, payload, kind = api.handle(request.method, url, body)
        if kind == "text":
            return PlainTextResponse(payload, status_code=status)
        headers = {}
        name = DOWNLOADS.get(request.url.path)
        if name is None and request.url.path.endswith("/raw"):
            name = "results.json"
        if name and status == 200:
            headers["Content-Disposition"] = f'attachment; filename="{name}"'
        return JSONResponse(payload, status_code=status, headers=headers)

    if (STATIC / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")

        @app.get("/")
        def index():
            return FileResponse(STATIC / "index.html")
    else:
        @app.get("/")
        def no_ui():
            return PlainTextResponse("QPV Workbench API is running, but the UI bundle is not built. "
                                     "Run `npm install && npm run build` in frontend/.")

    app.state.session = api.session
    app.state.api = api
    return app
