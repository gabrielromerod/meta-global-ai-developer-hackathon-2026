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


## Checkpoint after wave 2 component review (Nov 3, about 05:50 PT)

- W1 Shell/Home/Twin/Chat independently APPROVED (Home round1, others round2),
  task-only code and builder evidence merged into lead. W1 source aliases:
  Home35f5c6d; Twin4e524d1/3be77aa; Chat696aa77/ac2d828;
  Shell30fcd35/11e995b. Chat test-only async visibility fix5f717af is approved
  and merged as1a4f2a5. Rootnpm101 tests/build pass with Clips+Controls too.
- W2 Clips APPROVED round1 at review7c2ea321, evidenceeeb25a3a. Builder task
  commitsc820bb4,fdac312,31a673a,8f4ca05,a44fb69 merged; Rootlatest89161ad2.
- W2 Controls APPROVED round2 (reviewfrontend5f6f8893, docsUTF8ed4fe857),
  evidence835ca0cf. Builder1dbf554,c0dce4d,f6e05af,d8ba87b,8e74611a,
  612c9ea0,cc4aaf7b merged; Rootlatest83057d10.
- W2 Motion R1 CHANGES REQUESTED (own native hooklistener0→2→1).
  Builderfix47dddac6 removes libraryfallback; focused browsernow0→1→0,
  13motiontests. Await final builder QA-only HEAD then compose into rr-motion
  for r2_motion round2. R1 evidence84d3c278. Do not merge before approval.
- Current RootReactmain remains only foundation placeholder by design; old `/`
  stays usable. No root integration code written before all waves pass.
- Next is ROOT-ONLY INTEGRATION: API/Query/router/shared state; allpages;
  cachedcitedchat/localhousehold shared state; proper snapshot/sharing capability;
  native real video overlay/player clock synced with R3F and citations; typed
  owner/rulecallbacks. Keep `/next/` preview until final2freshreviewers approve.
- Motion leadintegration: replace Chat/Twin librarypreferencehooks with central
  reactivebridge; Chatactivepopup must also stop+set in-flight animation via
  useEntranceMotion/useAnimationControls (hookreplacementalone insufficient).
  R3F conepulse needs --v-motion-pulse period (currently literal1s). Add adequate
  internal scroll padding for floatingMessagespill, not a shorter scene.
- Use native HTMLvideo controls and existing mask/overlay knowledge; no fake
  canvas video when media unavailable. Newclip pages already render honest empty
  states. Preserve consentedphone voice WAV behavior and owner security via newUI.
- ExistingE2E24 still targetoldUI and must be ported to equivalentnewflows without
  weakened assertions. PrivateGLB never public; owner-only localpreview can retain
  import/compression validation, publicviewer mustrefuseprivategeometry.
- Full backend tests after review/metadata/capture work:1529pass, then1538pass
  after offline HTTP backstop. Exacttiming docs/timing. Rootlatestbackend3df3859c
  includes fullframepointbounds, camera review beforepointclient, Sam inlinepixel
  guard and actual pointmask boxadapter. No actualcamera connections.
- IMPORTANT INCIDENT: one invalid-key Meta POST happened in negativepointtest,
  returned401 (no successful inference, generated black JPEG, no owner key).
  Never againclaim zeroMeta requests forwhole rebuild. Remediation+evidence is
  in docs/readiness; all defaultPytests nowautouse strictrespx; live/hardware only
  explicitmarkersescape. Testalso has rejectingclient/cacheonly/closedloopback.
- UIprovenanceCI scan firstfailed5oldmanifestsbecausecapture-timefixture differs
  fromcurrent. Fixedbypinning exact historicalfixture snapshots withUNCHANGEDevidence
  hashes;12existingmanifestsnowvalidate. Currentui_evidence automaticallypins
  proof-fixtures snapshots. Futuremergedoldmanifestsneed exacthashsnapshotmigration,
  never re-certifywithdifferentdata. scripts/scan_ui_evidence.py gates everytracked
  QA media asset; fullworkingRootscan0failures beforeW2merges.
- Dockerlocalfullbuild passed, then Node24.15 supportedUIstage+78tests passed.
  CI frontendjob+DockerNodebuildadded. HostNode24.14 left unchanged. Repo isPRIVATE
  perghrepo view; GitHubplugin404metadata soCLI fallback used. RemoteCI coulduse
  billableminutes; do not trigger paidwork withoutownerdecision oncefinalSHAreviewable.
- User choseInter(c0f4942), noHub. No ML/go2rtc installed. Original10Python newline
  edits remain untouched. Never broadgitaddvigil/. Allcommands useexplicitad9eworkdir
  because managedworktree creation changes desktopactivecwd.
