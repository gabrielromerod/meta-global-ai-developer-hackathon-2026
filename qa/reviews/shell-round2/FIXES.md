# Shell builder response to independent round 1

Inter is the owner's selected font (`c0f4942`). Shell README and handoff now reflect
that choice; root QA notes remain lead-owned.

**P2 — card captions. REAL logic, FIXTURE browser evidence.** Reproduced at
1280×600 in both themes: all five cards clipped 139–140px of content. Shared
ClipCard now keeps its intrinsic content height and prevents its media/caption
flex children from shrinking. The containing review grid uses max-content rows,
start alignment and its existing internal scroll. Verdicts, titles and source
captions remain present. Implementation `ed5f73f`.

**P2 — notification dialog focus. REAL logic, FIXTURE browser evidence.** The new
complete keyboard regression initially failed with BODY focus. NotificationBell
now stores the selected visit until Radix's onCloseAutoFocus lifecycle: after the
menu item unmounts, it focuses the stable bell and opens the visit. The existing
Modal then records that bell as its external opener. Keyboard Escape and pointer
close return to the bell. Implementation `ed5f73f`.

**P3 — dropdown layering. REAL logic, FIXTURE stress evidence.** Reproduced the
reviewer's repeated-notification fixture with the menu at layer 30 and Messages at
40. Lead token change `673e9ad` (local cherry-pick `cd47680`) places the dropdown
at 45, above chat and below the modal. The tall footer and chevron are visible;
Open Attention remains clickable.

Red evidence is retained at qa/screens/5ae2259/shell-round2/before. The intermediate
cards/focus probe fails only on the unchanged layer token; the focused token probe
passes. Final matrix source is `ed5f73f`, under
qa/screens/ed5f73f/shell-round2/after. All 11 requested viewports cover keyboard and
pointer notification handoff, stress footer callback, and Clips/Media top/bottom
in both themes, including phone reflow. All card client/scroll differences are
zero, all keyboard returns target the bell, desktop document bounds remain fixed.

The same clipping and focus assertions ran before and after; none was removed or
reduced. npm test passed 40 tests and TypeScript/Vite build passed. No Python code
changed, so the unchanged Python suite was not repeated per lead direction.
New PNGs are generated UI only and are bound to the reviewed stress fixture and
lead-authored fixtures by the scoped metadata/decode/audio provenance manifests.

Pending independent round 2 review. This builder response is not approval.
