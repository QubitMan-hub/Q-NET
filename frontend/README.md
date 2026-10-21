# Frontend

The browser UI: React, TypeScript and Vite. It talks to the Python engine either over HTTP (`qpv serve`)
or, in the GitHub Pages build, to the same engine running in a Web Worker through Pyodide.

| Path | What it is |
|---|---|
| `src/` | The app: store, API client, panels and canvases. See `src/README.md`. |
| `e2e/` | Browser tests that drive the real UI against a running engine. |
| `index.html` | Page shell that Vite fills in. |
| `vite.config.ts` | Build config; output goes to `../src/qpvsim/server/static/` so `qpv serve` can serve it. |

```
npm install
npm run dev     # live-reload UI; start `qpv serve` alongside it
npm run build   # rebuild the bundled UI
```
