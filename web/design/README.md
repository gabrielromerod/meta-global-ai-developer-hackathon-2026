# Vigil UI contract freeze: vigil-ui/1

Lead owns this file and tokens.css after freeze. The executable JSON examples are in
`web/fixtures/`; endpoint contracts are in `docs/contracts/api.md`. They are authored
fixtures, never recorded camera/model evidence. Main stays on the usable legacy UI
until the lead integrates the independently previewable modules.

Use Preact + htm from `runtime.js`, not a CDN or build system. Preview HTML needs an
import map mapping `preact` to `/vendor/preact.module.js`; the main lead will do likewise.
All modules use named exports. All components use `html` tagged templates. UI labels
come from props or plain functional copy; no invented counts, people or activity.

## Ownership and exports

- A: `web/design/` except this README and tokens.css, `web/shell/`, `web/vendor/`.
  Export shared components from `web/design/components.js`; export AppShell from
  `web/shell/index.js`. Runtime and vendored files are already supplied.
- B: `web/pages/`. Export HomePage, AttentionPage, ClipsPage, LibraryPage, RulesPage,
  BenchmarkPage, SettingsPage from `web/pages/index.js`.
- C: `web/twin/`. Preserve createTwin(container, legendEl, twin) API and existing
  methods. Add optional fourth options object with onCameraSelect(cameraId).
  Add setPreset(name), dispose(), optional getOrbitState() for browser assertions.
- D: `web/chat/`. Export ChatPopup, ChatThread, MessagesPage from `web/chat/index.js`.

Agent-local preview HTML/JS and verification scripts belong within the owned paths.
Only the lead edits backend, contracts, fixtures, main entrypoint or cross-page state.
Requests and readiness may be appended to docs/coordination.md; timing rows may be
appended to docs/timing.md as the sole cross-path exceptions. Rebase hourly.

## Component props (single implementations)

- Icon({name,size?,label?}): vendored Lucide node data; decorative icons aria-hidden.
- Card({title?,actions?,className?,children}); Chip({children,tone?}).
- VerdictBadge({verdict,label?}): icon and text; normal/noteworthy/needs_attention/cant_confirm.
- Tabs({items,value,onChange,label}); items: {id,label}; callback receives id.
- VideoTile({camera,clip?,onOpen}); honest empty state when clip_url is null.
- ClipCard({clip,onOpen}); Timeline({events,time,onSeek}).
- Modal({open,title,onClose,children}); focus trap, Escape, restore focus.
- EmptyState({title,description?,action?}); Skeleton({label?}).
- Sidebar({route,onNavigate,household}); route ids: home,attention,clips,library,
  messages,rules,benchmark,settings. NotificationBell({items,onOpenVisit}).
- TopBar({title,evidence,notifications,onOpenVisit,theme,onThemeChange}).
- AppShell({route,onNavigate,state,theme,onThemeChange,onOpenVisit,chatSlot,children}).
  Shell contains Sidebar and TopBar, one main landmark and chatSlot overlay.
- Every B page receives {state,onOpenVisit,onOpenClip,onViewChange?,activeView?,
  twinSlot?,playerSlot?,visitSlot?,ownerSlot?,onSearch?,onRuleAction?}.
  Slots are rendered children; B never instantiates the imperative viewer/player.
  Home shows A-prime vs C role/rule difference from state.visits alone.
- ChatThread({thread,onSend,onShareClip,onSnapshot,onRecord,capabilities});
  ChatPopup({open,onClose,threads,selectedThreadId,onSelectThread,onSend,
  onShareClip,onSnapshot,onRecord,capabilities});
  MessagesPage receives the same thread props. onSend(threadId,text) is lead-owned.
  Thread messages: {id,author:'you'|'vigil'|'household',text,citations:[],clip_id:null}.

Presentational/local disclosure state is allowed. Domain state lives in lead-owned
useScenario/useEvents/useNotifications/useChat/usePlayerClock during integration.
Effects clean up. No fetching in render. No hidden fallbacks or fake actions. Controls
without implemented callbacks are disabled with an honest capability explanation.

## Visual rules

Dark-first, solid surfaces, blue accent, generous 8pt spacing, modern sans-serif,
rounded cards, thin open-licence icons, own simple house mark. No proprietary marks,
emoji, sparkle badges, marketing, gradients or fake users. Translucence/blur only on
overlays. Every visual value uses a --v-* token, dark/light. Request missing tokens.
Desktop shell is 100vh with no document scroll at 1440x900 and 1920x1080; constrained
lists may scroll internally. Narrow view collapses rail. Focus visible; keyboard
navigation; AA contrast; verdict always icon plus word. Reduced motion respected.

Home: 3D hero and camera tile slot, Attention 3–5 relevant visits, config-driven view
tabs. Unknown prefilter counts render an honest unavailable state. No invented 37.
Top bar has persistent small Demo data chip for fixture evidence, bell dropdown.
Floating Messages opens a popup on every page; sidebar opens same threads fullscreen.
Clips filter person/vehicle/package. Library text/camera/time/verdict search. Rules
show real fixture rules. Benchmark has unmeasured empty state, no invented metrics.
Settings holds owner token/check-in/Expected Windows; sandbox controls disabled with
exact label 'Owner-only on the home box' and B-prime's expected-window example.
Household messaging is local/mock only, labelled in code and visible UI. No fake
people, no people messaging backend. Ask-home uses cached ledger answers in Phase 2.

Twin: never underside, bounded zoom/pan, damping, animated front/left/backyard/top
presets, right-side tree barrier. No right topology path or blind region. Generic
massing without textures, house number, street/neighbours, distinctive details or
compass. Cones must stay above ground/outside walls. Event pulses, dotted gaps,
path drawing and hover blind labels must reflect actual input events/positions.
Preserve strict WebGL evidence; 2D is only an explicit runtime capability state.

## No shortcuts

Never weaken/skip/xfail tests, widen matchers, present synthetic output as real, mark
stubbed paths done, suppress errors, hardcode demo data in components, or leave silent
TODO/pass. Deferred requests go to coordination/readiness with a reason. Report
REAL/FIXTURE/STUB, test names, command, result, commit SHA. No Meta/cameras/spend.
No installs beyond approved pinned Reolink, Preact/htm/Lucide and ExifTool. Lead alone
merges after diff review, tests and browser screen inspection. Commit your own branch.
