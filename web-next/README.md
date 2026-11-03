# Vigil React app — frozen vigil-ui/1 contract

React + TypeScript + Vite. shadcn/ui wrappers use Radix, Tailwind, lucide-react,
Motion, TanStack Query, @react-three/fiber and @react-three/drei. No Preact.
Build: `npm ci` then `npm run build`. Dev: `npm run dev -- --port 8100`.
FastAPI serves the build at `/next/` while the existing `/` stays usable.

Lead alone owns contracts (`src/contracts.ts`), fixtures, tokens, root entrypoint,
package files, backend, and integration state. Fixtures are authored synthetic
data, never real-camera acceptance. No hard-coded evidence in components.

## Frozen exports

Shell: `shell/index.tsx` exports `AppShell({route,onNavigate,state,theme,onThemeChange,onOpenVisit,chatSlot,children})`.
Route IDs: home, attention, clips, media, messages, rules, benchmark, settings.
UI: `components/ui/index.tsx` exports Button, Card, Chip, VerdictBadge, Tabs,
VideoTile, ClipCard, EmptyState, Modal. Follow exported interfaces from contracts.ts.
Pages export named HomePage, AttentionPage, ClipsPage, MediaPage, RulesPage,
SettingsPage, BenchmarkPage from each owned directory's index.tsx.
Every page receives PageProps. Render lead-provided slots; no duplicate players.
Rules and Settings use optional typed ruleActions/ownerActions in contracts.ts.
Missing callbacks disable actions. Owner token entry is available only in edge mode;
check-in/window mutation additionally requires owner.enabled. Rule compile previews must
display the returned notice and remain distinct from owner confirmation. Consented phone
voice-rule fixtures/recording callbacks are separate from camera audio (never captured).
Twin: `twin/index.tsx` exports `HouseView({twin,positions?,time?,activeCameraId?,onCameraSelect?,preset?})`.
Chat: `chat/index.tsx` exports ChatPopup and MessagesPage, both receive ChatProps.
Floating/fullscreen messages share lead-owned state. Local people messaging is
labelled Local to this browser; ask-home uses cached cited evidence via backend.
Unsupported callbacks disable controls with an explanation.

## Isolation and review

Builders own only assigned source directories. Own tests/previews belong there too.
Standalone preview entrypoints can be reached through Vite HTML paths. No edits to
tokens, fixtures, contracts or package files: request changes in docs/coordination.md.
Append-only coordination/timing/QA notes and task-specific qa/ evidence are allowed.
Each worker runs its own Vite port from 8101 upward. Backend processes, if needed,
must use separate data directory, DB, cache and ledger. Never use cameras or Meta.
Use failing tests first; test behavior, not implementation strings. Commit work.

All visual values use --v-* tokens. Request missing tokens. Desktop 100dvh, internal
scroll only with stable scrollbar gutters; phone single column may scroll. Both
themes, visible focus, reduced motion, no false online states or invented metrics.
Verdict always icon and word. All user-requested viewports need actual screenshots,
opened and inspected. Findings end APPROVED or CHANGES REQUESTED. Three rounds max.
