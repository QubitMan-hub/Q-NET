# tests

Run with `pytest`. Browser tests in `test_ui_e2e.py` are skipped when Node.js, Playwright or the built UI is missing.

| File | What it covers |
|---|---|
| `test_engine.py` | Engine semantics: timing, deadlines, clocks, capabilities, loss, reproducibility. |
| `test_time_and_scheduler.py` | Time model, local clocks and the scheduler. |
| `test_quantum.py` | Both quantum backends, cross-checked. |
| `test_expr_and_validation.py` | Expression sandbox and project validation. |
| `test_qpv_core.py` | QPV building blocks: exact time, share combining, typed ports, geometry. |
| `test_qpv_protocol.py` | n-verifier QPV: scenarios, attacks against theory, auto-wiring, 1D compatibility. |
| `test_qpv_analysis.py` | Timing, light cone, verdict sentences and sweep presets. |
| `test_qpv_api.py` | QPV API routes over HTTP and in-browser transport. |
| `test_console.py`, `test_console_server.py` | Console commands, session API and server. |
| `test_regressions.py` | One test per bug found in review. |
| `test_ui_e2e.py` | Runs the `frontend/e2e` browser scripts. |
| `fixtures/` | Saved projects in the old format, to prove they still run. |
