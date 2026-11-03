# Independent mechanical cutover review A

REAL. Reviewed Root commit `060c583c0e11cd2cf8fdc0bfd8e6a16b18012f61`, applied as `934b6ed7` in this isolated review checkout. The diff changes static mounts and packaging, removes the retired vanilla/Preact UI and vendoring script, updates references/tests, and retains the independent LAN calibration worksheet. No reviewed React source changed. No actionable finding was observed.

FIXTURE. The actual isolated server at port 8198 asserted constructed cache-only settings, an invalid key, closed loopback model base and separate cache/SQLite/ledger paths before starting. `/` and `/next/` return identical bytes; every referenced built JS/CSS asset returns 200. Legacy app, owner, twin and Preact URLs return 404. `/api/ui/state` still returns 200, and `/calibrate/` remains blocked in sandbox. Browser navigation from `/` to the cited outsider visit works with no console errors or failed requests. Exact asset hashes and statuses are in `cutover-smoke.json`.

REAL. The 58 focused tests in `test_react_app.py`, `test_web_assets.py`, `test_ui_freeze.py` and `test_api.py` passed; they include sandbox calibration denial and owner-mode calibration availability. The actual root browser regression passed against the isolated server (one dependency warning). Ruff check and format check passed for the independent smoke script. The existing reviewed UI acceptance is unchanged and is not claimed as a new hardware or camera acceptance.

APPROVED
