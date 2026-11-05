# Curated product screenshots

Only two final screenshots are versioned: [Home](final/home.png) and [visit evidence](final/visit.png). They use explicitly labelled demo data; no camera footage appears. The source UI is the approved React release, with Inter.

All repository images together must remain below 10 MB. Working captures belong in ignored `data/qa/`; do not commit per-control or per-viewport archives. `scripts/scan_ui_evidence.py` enforces this policy and preserves provenance, pixel decoding, audio and metadata checks for the final captures.

Historical text review reports are retained. Their bulk screenshots, temporary scripts, logs and orphaned provenance snapshots are available in Git history rather than the working tree. This cleanup does not upgrade fixture acceptance to real-camera verification.
