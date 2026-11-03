# Vigil consumer UI: frozen contract vigil-ui/1

Frozen for visual workers. Only the lead changes contracts, tokens or fixtures. JSON
examples under web-next/src/fixtures are authoritative field examples, not live evidence.
All requests are same-origin. Errors are non-2xx JSON `{detail: string}` and must be
visible. No camera host, credentials or raw source URL is ever returned to a browser.
The existing API remains compatible. **The normalized /api/ui and chat endpoints are implemented and tested offline.
Isolated previews load fixtures; production integration uses same-origin queries.**

## Read API

| Endpoint | Response / behaviour | Current status at freeze |
| --- | --- | --- |
| GET /api/health | mode, synthetic, budget/config readiness; never a live connectivity probe | REAL |
| GET /api/ui/state | UIState below, optional session query; normalized from cached ledger/config | REAL logic / FIXTURE acceptance |
| GET /api/scenarios | legacy scenario summaries, synthetic label, session_start | REAL logic / FIXTURE sandbox |
| GET /api/visits/{id} | full visit detail as web/fixtures/visits.json visits[id] | REAL logic / FIXTURE sandbox |
| GET /api/visits/{id}/positions | positions, paths, unresolved gaps; no interpolation across gaps | REAL logic / FIXTURE sandbox |
| GET /api/twin | existing twin.json shape: cameras, generic site_plan, blind_regions, coverage, glb_url? | REAL logic / FIXTURE sandbox |
| GET /api/calls | cached model-call ledger | REAL logic / FIXTURE sandbox |
| GET /api/eval | existing evaluation report; authored values remain labelled synthetic | REAL logic / FIXTURE sandbox |
| GET /api/ui/search?q=&camera=&verdict=&start=&end=&kind= | `{contract_version,evidence,visits:[VisitRow],clips:[Clip]}`; intersect filters over cached ledger | REAL logic / FIXTURE acceptance |
| GET /api/ui/chat | web/fixtures/chat.json shape, assistant thread only server-owned | REAL logic / FIXTURE acceptance |
| GET /api/windows | `{windows:[ExpectedWindow],note:string}`; sandbox returns B-prime's recorded example | REAL logic / FIXTURE sandbox |
| GET /api/voice/fixtures | consented phone voice-rule fixtures; unrelated to camera audio | REAL logic / FIXTURE sandbox |
| GET /api/presets | current rule presets | REAL logic / FIXTURE sandbox |

Time query values start/end are ISO-8601 strings with timezone. Event/clip t0/t1/t
are session-relative seconds; clock is display-only. Never change recorded times.
Media URLs are same-origin paths to exported masked, silent, metadata-free assets;
null means unavailable and requires an empty state. No fake playable thumbnails.

## UIState

Required keys (all present in state.json):

- contract_version: literal `vigil-ui/1`; evidence: `{kind:fixture|real,label,source}`;
  mode: sandbox|edge|public; household: `{name,avatar_url:null|string}`;
  session: `{id,start}`. `fixture` displays the small persistent “Demo data” chip.
- cameras: `{id,name,model:null|string,power_profile:plugin_wifi|doorbell|battery_wifi|import,
  stream:sub|main|ext,status,source_label,hub_present:null|bool,wifi_signal_dbm:null|number,
  clock_offset_s:null|number,clip_url:null|string,thumbnail_url:null|string}[]`.
  Seven canonical IDs: front_left_duo,front_right_duo,doorbell,porch,side_left,
  backyard_1,backyard_2. No invented online status. Battery no-Hub uses Imported clips.
- views: `{id,label,camera_ids:string[]}[]`; include Overview, Day, Night, Front garden,
  Porch, Left passage, Backyard, then one per configured camera. IDs drive selection.
- summary: `{camera_events:null|int,on_property:null|int,visits:int,needs_attention:int,
  street_events:null|int,note:string}`. Null counts are unmeasured, never zero or fabricated.
- visits: VisitRow[]; attention_ids: visit IDs in relevance order; notifications:
  `{id,visit_id,verdict,story,clock,thumbnail_url:null|string,unread:bool}[]`.
- clips: Clip[]; events: Event[] with visit_id; rules: current RuleSpec JSON[];
  protected_objects: existing ProtectedObject JSON[]. No duplicate domain types in UI.
- benchmark: `{measured:bool,metrics:[],note}`; empty metrics = honest unmeasured state.
- owner: `{enabled:bool,reason,checkin_duration_s:120,windows:ExpectedWindow[]}`.
- capabilities: `{ask_home:bool,household_messaging:local_mock,snapshot:bool,
  recording:bool,owner:bool}`. A missing callback or false capability disables its action.

VisitRow: `{id,scenario,title,verdict,verdict_label,escalated,first_sentence,story,t0,t1,
clock,cameras:string[],gaps:string[],roles:string[],role_label,role_basis,reason,
thumbnail_url:null|string,clip_url:null|string,evidence_kind:fixture|real}`.
Verdicts: normal,noteworthy,needs_attention,cant_confirm. Display icon plus word.
Role is spatial code output, never identity. Home must show A-prime: Household,
egress basis, excluded rule/normal; C: External visitor, rule fired/needs attention.

Clip: `{id,visit_id,camera_id,verdict,clock,t0,t1,title,kind:person|vehicle|package,
clip_url:null|string,thumbnail_url:null|string,source_label}`. Clips without actual MP4
remain selectable visit evidence, with an explicit unavailable media state.
Event: existing serialized event `{event_id,t,t1,clip_t0,clip_t1,clock,camera_id,
camera_name,type,target:null|string,track_id,subject_id,actor_role,visit_id}`.
Detailed visit uses existing sentences/citations/events/rule_hits/subjects/trace/
expected_windows/watches/telemetry, shown exactly in visits.json. Its synthetic model
telemetry is not a measured benchmark and must not be promoted into UI metrics.

## Actions and owner security

All owner actions use existing `ownerFetch()` with X-Vigil-Owner from sessionStorage.
Never put the token in localStorage, URL, fixture, logs or generated HTML. Sandbox
controls are disabled with **Owner-only on the home box**. B-prime w3 remains visibly
a recorded expired window. No watch Undo exists until a genuine API implements it.

| Endpoint | Request | Response |
| --- | --- | --- |
| POST /api/checkin | `{}` via ownerFetch | existing single-use check-in with 120-second expiry |
| POST /api/windows | `{label,start,end,cameras:[],zones:[]}` | created ExpectedWindow |
| DELETE /api/windows/{id} | ownerFetch, no body | existing cancelled window result |
| POST /api/protect | existing full-frame camera_id, pixel coordinates and full w/h | existing protected-object result |
| POST /api/rules/compile | existing text / visit context contract | draft allowlisted RuleSpec |
| POST /api/rules/{id}/confirm | existing confirmation | confirmed rule |
| POST /api/visits/{id}/rerun | existing rerun context | recomputed validated visit |
| POST /api/chat/ask | `{thread_id:"ask-home",text:string,session_id:string}` | `{message:ChatMessage}`; cached-ledger search with event citations, no model call |

ExpectedWindow: `{id,label,start,end,cameras:[],zones:[],state,created_at,recorded?:bool}`.
Owner routes enforce existing origin/token/edge guards; no browser control bypass.
Recorded labels do not imply live SDK calls. No camera talk/listen/audio capture UI.
The existing consented phone voice-rule path is separate and keeps its guards.

## Messages

ChatEnvelope: `{contract_version,evidence,threads:Thread[]}`. Thread: `{id,title,
kind:assistant|local_mock,note,messages:ChatMessage[]}`. ChatMessage: `{id,
author:you|vigil|household,text,citations:[{visit_id,event_id}],clip_id:null|string}`.
Ask-home answers only from cached ledger, with citations or honest no-match result.
Household messages and shared cards stay in this browser; **no people messaging
backend**. UI and code label local demo clearly, no fake people or canned incoming
messages. Snapshot/recording disabled until lead supplies real backend capabilities.
No component embeds fixture data. Floating and fullscreen views share the same state.

## Viewer and assets

Preserve createTwin API and existing player APIs; sync via lead usePlayerClock in
Phase 2. C adds setPreset(front|left|backyard|top|right), dispose and optional orbit
inspection. Click camera callback selects a camera. Unresolved gaps stay dashed and
contain no guessed positions. Right trees are a physical barrier, not a blind region.
All geometry is generic public massing; no compass, street/neighbours, textures or
distinctive real-house scan. Private GLB may inform locate/coverage but must not leak
identifying geometry publicly. Duo detection uses full frame, halves only geometry.

## Freeze and integration policy

Workers preview fixtures only; no backend edits, shared hooks or cross-boundary
refactors. Lead implements normalized endpoints and state after all Part 5 items and
worker merges. Keep current app usable. Any unsupported path is MISSING in readiness,
not silently faked. Endpoint and field additions require lead contract revision.
