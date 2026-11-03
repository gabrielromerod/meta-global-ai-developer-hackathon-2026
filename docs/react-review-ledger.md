# React review ledger — FIXTURE acceptance

All screenshots use the requested numeric CSS viewport sizes, not claims of physical-device certification. Source SHAs are the independent reviewers' immutable composed checkouts; Root cherry-picked task/evidence commits without changing their bytes. Individual reports contain exact screenshots and verification scope.

| Task | Reviewed source | Reviewer evidence / verdict |
| --- | --- | --- |
| Shell/shadcn/fonts |330fd39|c269f0c — APPROVED round2; qa/reviews/shell-round2/ |
| Home/Attention |164b8c3|9f160742 — APPROVED round1 |
| R3F house |19ae451|14520ef — APPROVED round2; rendered framing/above-ground bounds |
| Messages |e1a4b35|bd67728 — APPROVED round2 |
| Clips/Media |7c2ea321|eeb25a3a — APPROVED round1; qa/review-clips-round1.md |
| Rules/Settings/Benchmark |5f6f8893, same production after docs encoding repair|835ca0cf — APPROVED round2; qa/reviews/controls-round2.md |
| Motion |5fbc14b1, same Motion tree as a79b8990|66496e97 — APPROVED round2 |
| Fresh final A round1 |9a8ced22|9e500d4d — CHANGES REQUESTED; qa/reviews/final-a/FINDINGS-round1.md |
| Fresh final B round1 |9a8ced22|87952bf5 — CHANGES REQUESTED; qa/reviews/final-b/ROUND1.md |
| Fresh final A round2 |0a7f99a1, production tree5cf05c57|cde38c03 — APPROVED; qa/reviews/final-a/FINDINGS-round2.md |
| Fresh final B round2 |c965bedf, production tree5cf05c57|80e217f0 — APPROVED; qa/reviews/final-b/ROUND2.md |

Root integration fixes are b906989f (transport/citations/presets/mic/clock/confirmation), a8329a47 (actual portal-mounted ordinary-motion popup) and5cf05c57 (persistent roving-wrapper focus ring). Every confirmed repair has a first-failing regression and actual browser verification where applicable; see QA_NOTES.md and tests/e2e/README.md. No tolerance, skip or expected failure was relaxed.

Both fresh final approvals authorized cutover060c583c to `/` and removal of the legacy consumer UI. Independent mechanical rechecks A9e3aa161 and Bd9a4e270 both APPROVED, with unchanged React source. Post-cutover full gates are recorded in timing.md. Camera/model acceptance remains separately missing by design; see readiness.md. This ledger does not authorize any model call, camera connection, install or spending.
