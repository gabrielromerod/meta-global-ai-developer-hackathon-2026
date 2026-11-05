# Curated product screenshots

Two screenshots are versioned: [Home](final/home.png) and [visit evidence](final/visit.png).
Home is the exact capture of `http://127.0.0.1:8000/#/home` that the owner reviewed and approved
on November 4, 2026, for this **private repository**. It contains masked property-camera
previews and a simplified house model. Its separate `home-privacy.json` records the owner's
approval against the exact image hash. The visit view uses labelled synthetic demo data,
with no camera footage, and retains its independent fixture provenance. Both are 1600 × 1000.
A future public release requires a new owner review of the Home image's publication scope.

All repository images together must remain below 10 MB. Working captures belong in ignored `data/qa/`; do not commit per-control or per-viewport archives. `scripts/scan_ui_evidence.py` enforces this policy and preserves provenance, pixel decoding, audio and metadata checks for the final captures.

Historical text review reports are retained. Their bulk screenshots, temporary scripts, logs and orphaned provenance snapshots are available in Git history rather than the working tree. This cleanup does not upgrade fixture acceptance to real-camera verification.
