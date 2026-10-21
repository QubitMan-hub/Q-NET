# End-to-end browser tests

Playwright scripts that drive the real UI and check it against the engine. Start `qpv serve --port 8765` first
(or serve the Pages build for `static.mjs`). Each takes the URL and an optional screenshot folder.

| Script | What it checks |
|---|---|
| `run.mjs` | What the UI shows equals what the engine API reports: stepping, events, inspector edits, console, experiments, timing, light cone, 3D view and the Play panel. |
| `build.mjs` | Builds QPV_BB84 from an empty project using only the graphical editor, runs it and saves it. |
| `audit.mjs` | Opens every scenario, view and tab, in both themes and several screen sizes, and reports browser errors and broken UI. |
| `static.mjs` | Smoke test of the GitHub Pages build, where the engine runs in the browser. |
