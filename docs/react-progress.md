# React and seven-camera implementation ledger

Current lead checkout: `C:/Users/lords/.codex/worktrees/ad9e/meta-global-ai-developer-hackathon-2026`.
Branch `codex/react-seven-cameras`. Preserve the original ten Python line-ending edits;
they are not task changes. No camera calls, paid flags, ML packages or go2rtc installs. One invalid-key Meta authentication request occurred in a negative test; docs/readiness.md records the incident and strict offline HTTP backstop.
Owner confirmed **no Home Hub**: all three battery cameras use imported clips.

## Lead commits

- d12a114: React foundation + `/next/` mount; existing `/` retained.
- 695ed91, 5d786a4: shared tokens/contracts/position fixture additions.
- b6e2199: fail-closed metadata scanner; exact v_ap reason fixture cleanup.
- 86cbdca: seven-camera config, unmeasured routes, privacy review, Duo, import,
  event capture/retention, doctor, schema illumination migration; all offline evidence.
- 5caa22d, 4f03c23: normalized cached UI state/search/events/notifications/clips/chat.
- edacc8c, 685bef5: shared EXIF guard and hash-bound portable UI screenshot provenance.
- a18ebe2: AC-only restream profile and seven-host env example.
- c8f765c: public generic massing, no private GLBs in real exports; normalized positions.

Baseline: 1473 passed, 24 E2E deselected. Migration failures were fixed without loosening
assertions. A later full run had 1501 pass and one deterministic bundle mismatch;
bundle regenerated and that test passed. Current full backend/E2E compatibility run
is in progress; exact starts/ends are appended by its runner to docs/timing.md.

## Wave 1 builders (complete; not approved yet)

All worktrees live under `C:/Users/lords/.codex/worktrees/<name>/meta-global-ai-developer-hackathon-2026`.

| Task | Agent | Worktree / branch | Owned commits / final HEAD |
| --- | --- | --- | --- |
| Shell/UI/fonts | w1_shell | rx-shell / codex/react-shell | c9e5dec, 7bd6dd3, 3a0e872, 53a6fb0, 031c524, 79e6d0f, b246e20, 5ae2259 |
| Twin | w1_twin | rx-twin / codex/react-twin | 0733a2a..20d2a25 (0733a2a is duplicate of lead 695ed91; exclude it) |
| Home/Attention | w1_home | rx-home / codex/react-home | 07effdd, 5674ab3, b613fc1, 4fc0631, 7be158f, 58a6098, 63cea76 |
| Chat | w1_chat | rx-chat / codex/react-chat | 70a0c16, cc76686, 43a2ea1, 9cc0857, 4f5f036, a70abff, a1a7006 |

Do not merge duplicate dependency cherry-picks from builders. Root owns fixtures,
contracts and tokens. Shell/Home review trees include latest exact Twin source plus
root fixtures (v_ap copy fixed at b6e2199). Source and screenshot SHA may differ;
each evidence README records both.

## Independent review round 1 (active)

| Agent | Worktree / branch | Reviewed composition | Port |
| --- | --- | --- | --- |
| r1_shell | rr-shell / codex/review-shell | 1e22d6b | 8111 |
| r1_twin | rr-twin / codex/review-twin | e9c3626 | 8112 |
| r1_home | rr-home / codex/review-home | 164b8c3 | 8113 |
| r1_chat | rr-chat / codex/review-chat | e16c219 | 8114 |

Provisional findings, awaiting consolidated verdicts: Shell notification-dropdown
opener unmounts and dialog loses return focus; Twin actual controls pan beyond bounds
and phone top preset crops; Chat short popup empty text clips and help text has mojibake.
Home behavior probes passed so far. No task is approved yet. Three review rounds max.

## Next work

- Send consolidated CHANGES REQUESTED to owning builders; re-review, merge approved
  task-only commits into lead and start wave 2 as slots free.
- Wave 2: Clips/Media; Rules/Settings/Benchmark; Motion. Each isolated + independent review.
- Root-only integration follows approved waves: Query/shared state, owner routes,
  cited chat, real player/3D/card clock sync, final two fresh reviews, switch `/`, remove old UI.
- Port existing E2E to equivalent new workflows without reducing assertions; explicitly
  preserve consented voice-rule behavior, owner security, cited traces and generated video.
- Full suites with exact times before main merge; screenshot provenance/metadata/privacy
  gates on all committed assets; update readiness and requirement traceability honestly.
- Backend audit follow-ups: persist actual prefilter counts when measured, exercise full
  generated Duo cloud chain, use nominal half-FOV in homography projection, replay event
  service orchestration with injected adapters, validate all export media before copy.

## Evidence tooling

`scripts/ui_evidence.py` is lead-owned. Use its absolute lead path from worker checkouts.
It validates named manually reviewed static UI PNGs against null-media fixture hashes,
exact PNG hashes, PNG decoding/no audio and batched metadata. Fixture paths are portable;
fixture hashing normalizes only CRLF to LF. Ordinary footage stays on strict camera masks.
Untracked draft screenshots remain in workers; do not delete user data. Two workers'
automatic approval review rejected draft cleanup as "blocked by policy" without details;
safe outcome was to leave drafts untracked and commit only final evidence.
