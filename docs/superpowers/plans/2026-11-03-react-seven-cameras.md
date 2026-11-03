# Vigil React and seven-camera implementation plan

> **For agentic workers:** Use the owner's reviewed parallel-wave process; apply TDD and independent review.

**Goal:** Replace the app with reviewed React UI and prepare guarded offline-capable capture for seven Wi-Fi cameras.
**Architecture:** FastAPI serves a normalized cached evidence contract and a Vite build. Camera ingest stays privacy-blocked until owner review; code alone links and decides.
**Stack:** React, TypeScript, Vite, Tailwind, Radix/shadcn, Lucide, Motion, TanStack Query, R3F/drei, existing Python backend.
**Spec:** docs/spec/vigil-spec.md plus the owner's Nov 3 task message.

## Constraints and review focus

No live Meta or camera calls, no spend. No raw media, audio, identifiers or guessed gaps.
Test first, never weaken tests. Preserve current `/` until final approval.
Review empty evidence, clock drift, battery wake gaps, Duo seams/night colour changes,
and short Wi-Fi clips. Check every requested viewport, both themes, keyboard focus,
all interactions, above-ground orbit and reduced motion. Unknown is never zero.

## Tasks

- [ ] Freeze React contracts/tokens/fixtures; test `/next/` static serving before adding mount.
- [ ] Wave 1: four isolated builders (shell, twin, home/attention, chat), followed by four independent reviewers.
- [ ] Lead backend 1: enforce metadata scanner, prove dirty metadata detection and missing-tool failure, run CI-equivalent checks.
- [ ] Lead backend 2: seven-camera config/topology, test no right-side route, unmeasured transit and outer-ring filtering.
- [ ] Lead backend 3: panoramic detection/geometry, remove plate OCR, test generated MP4 and night modes.
- [ ] Lead backend 4: review gate, masks, silent metadata-free exports, per-frame generated Duo privacy proof.
- [ ] Lead backend 5: Hub detection/import policy, timestamped guarded battery import.
- [ ] Lead backend 6: event pre-roll and pinned retention/free-space/cache cleanup.
- [ ] Lead backend 7: doctor profiles, Hub, review, drift and exiftool diagnostics.
- [ ] Lead backend 8: normalized state/search/events/notifications/clips/chat from real cached ledger.
- [ ] Wave 2: clips/media, rules/settings/benchmark, motion; independent reviews, three rounds maximum.
- [ ] Integrate query/state/player/twin/chat, full regression suites and two fresh full-app reviews.
- [ ] Switch `/` after clean final review; remove old UI, scan and commit screenshots, record offline limits.

Each backend task starts with a failing behavioral test in its existing spec-named
test file (or a focused integration extension), implements the minimum, runs relevant
checks and reviews coordination and QA notes before moving on. All suites and times
are recorded. Real hardware/model acceptance remains owner-dependent and never Verified.
