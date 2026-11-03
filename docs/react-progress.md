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


## Integration checkpoint, Nov 3 06:29 PT

All seven wave tasks APPROVED, including Motion round2 (review66496e97/source5fbc14b1). All approved reviewer evidence (Shell c269f0c, Twin14520ef, Home9f160742, Chatbd67728, Clipseeb25a3a, Controls835ca0cf, Motion66496e97) is merged into the root branch.

Root React production integration is implemented at `/next/`; old `/` remains usable until final two-reviewer approval. Core49782952, owner inventory fixb8ac1988, Day/Night schematice1d4a6e7, scene-height/voice-label fix25509839, floating Messages focus+143-PNG evidencee2b2b168. API visit detailf4b90be0 normalizes player/citation IDs. React Router HashRouter, TanStack Query, shared popup/fullscreen threads/drafts, local-only household messages, cited cached chat, real native-video playback/SAM overlay/shared clock/citations/3D, decoded PNG snapshot, cached voice fixtures and in-memory PCM16 phone recorder are wired. All UI model requests explicitly cached. No live model controls enabled.

Tests:125 frontend tests and build pass; six new React E2E flows pass (15.33s): Home A′/C, real owner token/countdown/window CRUD, voice samples+server scope notes, popup/fullscreen drafts/local-household+cited assistant, generated MP4 decode/seek/overlay/snapshot, SVG fallback cameras/gaps/right-tree barrier. Full backend1541 passed,29 deselected,150.10s; start06:23:16.505545/end06:25:47.752473 PT. Counts are exact observed; the map E2E was added after collection, so next collection has30 E2E total before any further tests.

Root integrated 132-state layout smoke: all11 exact CSS sizes×both themes×six pages, no document overflow/page errors/HTTP or network failures, scene>=180px. All11 sheets opened, selected full originals inspected;143-PNG gate0failures. Committed qa/screens/cb80f501. Before-fix evidence2PNGs gated/committed qa/screens/e1d4a6e7; other draft PNGs left untracked and locally excluded without deletion. This is a layout smoke, NOT final independent full-control approval.

REMAINING: finish shared tap-to-protect integration honestly against actual exported stills/cached results (no made-up frame/mask), preserve any remaining relevant legacy behavior; port existing24 legacy E2E tests to equivalent React workflows WITHOUT weakening tests, documenting explicit new privacy/honesty requirements (public renderer must never load private GLB; missing video must never be a fake canvas). Add real multicamera MP4 synchronization proof where synthetic canvas assertions no longer apply. Then two FRESH final reviewers on isolated worktrees/ports/data/ledger; fix findings; switch `/` only after approval and remove old UI. Full suites+Docker/privacy/metadata/provenance/gitleaks and exact timings before main integration. Rewrite stale readiness/requirements docs honestly. Private hosted CI may spend minutes: ask owner only when final concrete SHA is reviewable, if required; no push/hosted paid action yet.

Known source followups: Chat zero-thread pending/error copy currently says No threads available (should distinguish loading/error); no new queued Chat test yet. Owner windows created in seven-camera config now validate configured IDs; API recorded-window camera aliases may need normalization. Root new UI code is compact TS style like existing components; could format if tooling chosen. Native snapshot ready race fixed via loadeddata/canplay/seeked events. Floating pill remains mounted hidden while popup opens, enabling exact focus restoration. Day/Night only schematic illumination; never relabel recorded clips. SVG fallback added with first-failing unit/E2E tests and no position inside gaps.

No fresh final reviewers spawned yet. All current child agents completed. Root server8000 still active, sandbox/cache-only/invalid key/closed-loopback model base. No camera connection. One earlier invalid-key Meta HTTP401 incident remains documented; never claim zero Meta requests for whole rebuild. Original10 Python newline edits remain unstaged/untouched.


06:44 PT followup: shared tap-to-protect is now implemented in Settings owner controls, using actual exported PNGs, keyboard/image coordinates, cached-result honesty and explicit cost confirmation for a future owner action. Unauthorized/cache-only preview stays locked. GET/ui/protection-frames rechecks image privacy/metadata; the tampered-frame regression fails closed. New protected results join the server-session catalogue. Existing server-session persistence semantics are clearly labelled, not claimed durable. This supersedes the earlier blanket no-live-controls note: no AUTOMATIC live request exists; the gated future point action was tested only via injected FakeBackend. Frontend128 tests/build pass;20 export/consumer/point backend tests pass; seventh React E2E (actual exported still + fake model approval) passes9.08s. Full default suite1541 was run before these export additions, so final full rerun remains required.


## Final review round one / repair checkpoint, Nov 3 about07:24 PT

Fresh reviewers A/B worktrees rf-a/rf-b branches codex/review-final-a/b, ports8118/8119, reviewed immutable9a8ced22. A CHANGES REQUESTED six findings, evidence9e500d4d,217 gated PNGs,198-layout-state pass. B still finishing independent R1; also found mic setup cleanup, compiled CSS time-unit conversion, initial-reduced timing refresh and chat citation event loss. Their full media PNGs stay untracked; only media-free labelled diagnostic crops with exact observed fixture JSON pass unchanged gate. No black-image/media exception was added.

Root repairs are ready for combined R2 after focused gates: native Play/Pause/focus wired to shared transport, actual video is master clock, seek/transport effects separate (no RAF autoresume); two genuine generated MP4s preserve original0.2s drift bound and native keyboard controls. Initial chat pending/error are explicit and retry calls Query.refetch. Confirmation consumes top-level returned rule, clears draft, and edge note is mode-accurate. Group preset props are requests keyed by outer view, then manual presets work. Recorder releases partially acquired streams/contexts and late grants after disposal. Recorded clocks preserve session_start ISO offset and display date/zone, tested UTC/Tokyo/LA. Narrow R3F toolbar moves zoom/coverage/reset into existing Radix menu without squeezing scene. Motion and R3F share timeSeconds parser for ms/s after minification; palette refreshes on OS preference, camera preserved. Chat citations carry event_id into hash route and select normalized event/camera after load.

Current known gates:134 frontend tests/build pass;18 integrated React/real-video E2E pass in55.79s. Whole-root Ruff check/format pass (273files). Full backend1541pass was before PNG export/protection route additions; repeat final full suites later. Legacy24 E2E port is still unfinished except actual-video test now targets /next; new multicamera test is added. Root must port judge/mobile/owner/GLB workflows without weakening intent, including stronger privacy (public renderer never loads private GLB) and honest missing video (no synthetic playable canvas). Do not remove tests to get green. No fresh reviewers should be sent partial repairs: provide immutable combined repair SHA, then their exhaustive R2 interactions/all sizes. Root cutover/removal waits for both clean approvals.

Runtime safety: Root old server62919 was stopped; new session78243 on8000 asserts actual Settings sandbox/cache_onlyTrue/closed-loopback base/invalid key BEFORE launch, watches only vigil/. Correct env names VIGIL_META_CACHE_ONLY/VIGIL_META_BASE_URL/VIGIL_CACHE_DIR. Docker/CI/runbooks already had correct names. Root QA ledger model_calls count0, checked read-only. Earlier progress-note shorthand was ambiguous, now actual values verified. B restarted8119 with same verified prefixes and ledger count0; A was asked to verify. Earlier invalid-key Meta401 negative-test incident remains the only known agent Meta request and stays documented. Never claim zero Meta requests for the whole task.

All Root commands explicitly workdir ad9e; desktop native cwd is now rf-b after creating final reviewer worktrees. Original10 newline-only Python edits remain unstaged. Current Root integration branch codex/react-seven-cameras, not main. No hosted CI/push/real cameras/ML installs. Inter and no-Hub decisions final.

07:29 PT superseding R2 hotfix: B found ordinary-motion ChatPopup remained opacity0 because the entrance hook started before Radix mounted the portaled motion node. A was told not to finalize known-broken b906 R2. Popup content is now a forwarded child that mounts its hook with the portal; computed-opacity/transform browser regression failed first and now passes, including live reduce↔ordinary same draft/input/focus.21 related frontend tests/build and focused E2E pass. No gate expansion or actual Meta/camera/mic request. A/B need this hotfix atop b906 for final R2 source.

07:45 PT followup: full migrated React E2E suite43 passed in79.26s (07:39:18.758670–07:40:39.366738 PT). Original24 cases remain represented; stronger no-private-GLB/no-fake-video requirements and actual recorder/WAV paths documented in tests/e2e/README.md. Provisional tabpanel focus issue was rejected after real Tab showed existing2px ring; no panel production change. A then confirmed a distinct persistent Radix roving-tablist wrapper focus state with inline outline:none. Root defensive entry-focus regression failed first; tokenized inset list shadow now passes alongside unchanged panel focus test. This is a small R2 addon; production source otherwise stays a8329a47.

08:37 PT release preparation: full Linux suite from committed Git bytes passed1543 tests,44 E2E excluded,177.19s, networkdisabled. Previous4 Linux metadata failures were the test-context Windows trailing CR, not committed script logic; new LF invariant protects working copies. CI now shares frontend artifact with backend tests and scans TypeScript fail-closed. Hosted CI remains untriggered; GitHub quota API was unreadable without extra user OAuth scope, which was not requested. All44 E2E pass against verified local Docker. Main remains be264a4; both final reviewers still R2 (no new blocker currently), UI source5cf05c57 unchanged.


## Reviewed root cutover, Nov3 about09:01 PT

Both fresh final R2 reviewers APPROVED production tree5cf05c57: A evidencecde38c03 and B80e217f0 are merged. Cutover060c583c now serves the exact dist at `/` and `/next/`, removes legacy web/ and obsolete Preact vendoring script, preserves only the standalone private LAN worksheet under tools/field-calibration/. A independently APPROVED this mechanical diff (9e3aa161, merged27eda664); B mechanical check is pending. Post-cutover full backend1543 pass170.96s; complete browser45 pass86.57s; reviewed Docker45 pass86.64s; frontend134/build and Ruff pass. Root132-state all11 sizes/both themes pass, manually inspected contact sheets/full-size phone Home,132-PNG provenance0 failures. dd77d169 fixes Windows scan to call the same shared Python metadata scanner without WSL; actual PowerShell scan passes (zero demo media, not footage acceptance). Main QA ledger remains0 rows and all7 privacy approvals remainfalse. No camera connection or successful Meta inference. Hosted CI spending decision remains owner-only; do not claim hosted green or main merged before it happens.

09:04 PT: B mechanical cutover APPROVEDd9a4e270 mergedcbfa19ef; both final and mechanical reviews are clean. Full combined prior-evidence audit finished0 failures (45,990PNG); Root132 and B2 current-root PNGs each pass their unchanged supplemental gates (46,124 trackedPNG total). Root complete local release gates are green, sourceReact unchanged since5cf05c57. Hosted CI awaits spending decision before workflow execution; feature push is branch-filtered and starts no hosted jobs.

10:14 PT publishing checkpoint: four ancestor batches accepted over SSH/HTTPS; combined final wire pack expanded to2.07GiB and failedHTTP500 at the documented2GiB bound. Split chunked transfer then returnedHTTP408; no remote ref advance was claimed. Larger delta window did not reduce the wire pack (2.07479GiB;277.4s local check). A per-command HTTP/1.1 fixed-length1.5GiB buffer acceptedbbe59e37 at10:14:11 PT; finaldaacee9c batch follows. Source/asset bytes and branch ancestry are unchanged, no persistent Git setting was changed, and no hosted workflow was triggered. Extra read-only review-A history check found all28,514 media assets identical to checked release copies and Gitleaks7 commits/14.44MB clean; no extra review branch was published. Main stillbe264a4a pending the owner's CI spending decision.
