# Use cases and user flows

Condensed from [spec section 3](spec/vigil-spec.md#3-use-cases-and-user-flows). Each use case links to its full text (trigger, preconditions, main flow, alternatives, errors, outcome).

## Journeys

The four journeys carry Vigil's value and the demo. Use cases are the steps they are made of.

| Journey | What the user experiences | Use cases | Demo |
| --- | --- | --- | --- |
| **J1** | Protect an object and set a rule (spoken, sample audio or typed), then catch the night visit with an honest gap, while a household member's touch of the same gate stays quiet | UC-02, UC-03, UC-06, UC-07 | Scenarios A′ and C, judge steps 2 to 6 |
| **J2** | A delivery makes Vigil start watching the package on its own; inside an owner-set delivery window the courier is an expected visitor | UC-05, UC-08 | Scenarios B and B′ |
| **J3** | A judge checks any claim in one click | UC-07, UC-09 | Judge steps 3, 4, 8 |
| **J4** | At home, a person walking into the backyard appears in the 3D model as a camera event at once, then as a tracked position | UC-10, UC-11 | Live home clip in the video only |

## Actors

Full table: [spec, Actors](spec/vigil-spec.md#actors).

| Actor | Goal | Touches |
| --- | --- | --- |
| Owner | Fewer, better alerts; protect what matters | Visit cards, tap-to-protect, rules (voice or typed), expected windows, "I'm outside" check-in (LAN) |
| Installer or homeowner (at setup) | Cameras, privacy polygons, zone kinds, topology, clock offsets, scan and landmark alignment | `cameras.yaml`, `vigil ingest`, `vigil spatial`, `web/calibrate/` |
| Judge | Check that it works and that claims hold | Hosted sandbox |
| Visitor or household member | None; recorded subjects, given a role by spatial origin only (never identified) | Masked, consented footage only |
| Meta Model API | Perception and language | Called by Vigil only, Standard mode |

## Use cases

| ID | Name | Actor | Trigger | Outcome | Requirements | Full text |
| --- | --- | --- | --- | --- | --- | --- |
| UC-01 | Set up a home | Installer | First run | Valid config, offsets stored | FR-001 to FR-003 | [UC-01](spec/vigil-spec.md#uc-01-set-up-a-home-installer) |
| UC-02 | Protect an object | Owner | Taps an object on a still | Protected object `po_N` active | FR-019 | [UC-02](spec/vigil-spec.md#uc-02-protect-an-object-owner) |
| UC-03 | Create a rule | Owner | Speaks (hold the mic), taps one of the 3 sample-audio buttons, or types | Active rule `rN` with its `applies_to` badge | FR-021, FR-022, FR-012, FR-044 | [UC-03](spec/vigil-spec.md#uc-03-create-a-rule-owner) |
| UC-04 | A routine visit | System | Motion on cameras | Grey Normal card, no alert (proves alert reduction) | FR-005 to FR-016 | [UC-04](spec/vigil-spec.md#uc-04-a-routine-visit-system) |
| UC-05 | Expected visitor and the closed loop | System | Courier leaves a package | Noteworthy card; "Now watching: package on porch" | FR-013, FR-014, FR-020 | [UC-05](spec/vigil-spec.md#uc-05-an-expected-visitor-and-the-closed-loop-system) |
| UC-06 | Rule broken with a blind spot | System | Night touch on the side gate, 41 s behind the shed | Needs your attention card with a labelled gap | FR-008, FR-011, FR-012, FR-015, FR-016 | [UC-06](spec/vigil-spec.md#uc-06-rule-broken-with-a-blind-spot-system) |
| UC-07 | Review evidence | Owner or judge | Opens a card | Every claim checked in 1 click | FR-017, FR-018, FR-023, NFR-018 | [UC-07](spec/vigil-spec.md#uc-07-review-evidence-owner-or-judge) |
| UC-08 | Package taken | System | Person overlaps the watched package; package track ends | `removed` event; default rule fires; Needs your attention (Noteworthy for an `expected_visitor` under an `external_visitor_only` rule) | FR-008, FR-012, FR-029, FR-044 | [UC-08](spec/vigil-spec.md#uc-08-package-taken-system) |
| UC-09 | Judge explores the sandbox | Judge | Opens the URL | Full judge path, cached and live | FR-026, FR-027, FR-040 | [UC-09](spec/vigil-spec.md#uc-09-judge-explores-the-sandbox) |
| UC-10 | Place the cameras in the 3D model | Installer or homeowner | First run or a camera moved | Product path: LiDAR loops, nominal FOV, SAM 3.1 proposes landmarks, 6 taps per camera, PnP (target under 5 min per camera, not yet measured). Audit harness (benchmark only): 6 surveyed markers per camera, never used in the solve | FR-035 to FR-038, NFR-024 to NFR-026 | [UC-10](spec/vigil-spec.md#uc-10-place-the-cameras-in-the-3d-model-installer-or-homeowner) |
| UC-11 | Live monitoring at home | Owner | Someone walks into the backyard | Presence at once; the cited picture shortly after | FR-030 to FR-034, FR-039, FR-040 | [UC-11](spec/vigil-spec.md#uc-11-live-monitoring-at-home-owner) |

### Key alternatives and errors (one line each)

- **UC-01:** SAM proposes a polygon from a concept prompt such as `street`; an edge naming an unknown camera fails with the line number; a camera with no sync event is excluded until fixed.
- **UC-02:** wrong mask means tap again (second or negative point, or a box); zero matches means "Nothing found there, try tapping the centre of the object"; API down means preset objects in cached mode with a notice.
- **UC-03:** "anyone except family" compiles to `applies_to: non_household`, "strangers only, not deliveries" to `external_visitor_only`; a named person ("except Sam") compiles to `non_household` with "Vigil can't recognise individuals"; the draft card says household means seen coming out of the house's own doors or checked in on the app, and that household members arriving from the street without a check-in count as non-household. Unknown target asks "Which object do you mean?"; no microphone means the sample-audio buttons or typing; a failed transcription leaves an editable empty transcript; two compile failures fall back to form fields with an `applies_to` selector.
- **UC-05:** an off-allowlist watch proposal is logged as rejected; no watch is created.
- **UC-06:** an uncited Wonder sentence ("he checked the shed door") is rejected, retried once, then templated.
- **UC-08:** a person who arrived from a perimeter zone in the scope of an active Expected Window, under an `external_visitor_only` rule, gives a Noteworthy card with `role_basis: window:<id>`. "This was expected" afterwards is feedback only and never changes a verdict.
- **UC-09:** a failing API shows "Live call failed; recorded result from \<date> shown"; a reached cap shows "Live budget for today used; recorded result shown"; cached mode still works and buttons stay active.
- **UC-10:** too few landmarks visible means a temporary landmark (a box or chair, scanned once); landmark reprojection over threshold drops the worst point and SAM proposes more; failed registration aligns segments to a tape-measured site plan; an unusable scan means the site-plan model. If the audit shows a camera misses NFR-024, record a lens profile for that camera model and re-solve.
- **UC-11:** a camera drop turns its cone grey ("Camera offline") and stores an outage gap; a slow API grows the on-screen lag but the pulse still works; off the home network nothing is reachable, by design.

## Global error scenarios

Full table: [spec, Global error scenarios](spec/vigil-spec.md#global-error-scenarios). The test names are binding for the owning workstreams.

| Error | Where | Handling | Test |
| --- | --- | --- | --- |
| SAM returns zero matches | FR-006 | Empty track list; window marked processed | `test_sam_parse_empty` |
| More than 16 objects in a window | FR-006 | Split the window in half and re-run | `test_sam_window_split` |
| SAM 400 (aspect ratio, prompt) | FR-006, FR-019 | No retry; log the body; show a message | `test_sam_400` |
| 429 or 5xx | all calls | 2 retries with backoff and jitter, then fallback | `test_client_retry` |
| Wonder output not valid JSON or schema | FR-014 | Counts as a validator failure: retry once, then template | `test_wonder_malformed` |
| Camera clocks drift | FR-002 | Re-sync per session; reject sessions over 0.5 s residual | `test_sync_residual` |
| Spend cap reached | FR-026, FR-043 | Live request served from cache with the notice | `test_spend_cap` |

Related: [demo happy path](demo-happy-path.md), [requirements checklists](requirements/functional.md), [state machines](architecture/README.md#59-state-machine-visit-lifecycle).
