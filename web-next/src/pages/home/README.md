# Home and Attention task evidence

The pages consume `PageProps`; the lead owns API queries, selected visit state,
the player and the house scene. Home renders each supplied slot once. No page
fetches, infers a role, identifies anyone or computes a verdict.

The Home preview uses at most five code-ranked visit IDs. The full Attention
page keeps every ranked visit and offers verdict filters. Both drop missing IDs
and deduplicate repeated IDs without changing relevance order.

The touch comparison selects two existing touch events on the same protected
object, with their supplied spatial roles, code verdicts, clocks and rule reason.
If either side is absent it renders no comparison. It never fabricates a paired
visit. Unknown prefilter counts remain unavailable; a measured zero stays zero.

Preview: `npm run dev -- --port 8103`, then open
`http://127.0.0.1:8103/next/src/pages/home/preview.html`.
The preview imports the shared shell and twin checkpoints and loads authored
fixtures. It is FIXTURE evidence, not a real-camera or real-model acceptance.
Unsupported preview routes show an explicit task-scope empty state; production
routing belongs to the lead. The preview evidence dialog is not the final player.

Run `npm test`, `npm run build`, and (with the preview server running)
`node src/pages/home/qa.mjs`. The browser runner uses all eleven numeric CSS
viewports from the owner prompt, in dark/light, and saves hover, keyboard focus,
tabs, filtered lists, dialogs and scroll-end states. It checks page overflow,
scene space for every view selection, opener focus restoration, console errors
and failed requests. Physical device/browser chrome is not claimed as tested.

The short desktop layout puts the context pair beside the hero at heights up to
820 CSS pixels; this keeps the scene meaningful at scaled Windows and 4:3 sizes.
On phones the context pair and attention evidence precede the house in DOM and
visual order, with normal document scrolling. The first C verdict/story and both
comparison verdicts remain visible in the initial 390×844 view.

Evidence input: normalized fixture reason for `v_ap` is copied byte-for-byte from
lead commit `b6e2199`, while the task commits only owned page paths. The lead must
keep that fixture revision when integrating this task.

REAL: data selection, callbacks, supplied-role/verdict display and responsive
layout logic on real-shaped inputs. FIXTURE: all screenshots and the current
demo stories. MISSING for this task: API/state/player integration, owned by lead;
hardware/model acceptance requires the owner's separate approved field run.

The final image gate is the lead's `scripts/ui_evidence.py`: its `ui-privacy.json`
binds every PNG and fixture hash, checks fixture media/avatar URLs are null,
decodes PNGs, checks audio absence and scans metadata in batches. Fixture paths
are portable and fixture hashes use explicit LF normalization. The default
camera-frame scan was run and failed because app screenshots do not map to a
camera. No camera mask check was loosened. An additional documented unmapped
audio scan and metadata scan passed. `evidence-inputs.json` binds the lead fixture
revision; the twin is generic massing with no GLB and no footage appears. Local
gitleaks is unavailable; CI owns that check.

Visual dependency finding for the Twin owner: the selected-camera 1024×768 frame
can still clip lower labels with full Twin controls in a narrow 440px parent,
despite passing Home's 180px scene guard. Evidence is
`qa/screens/58a6098/four-three-1024x768/home-dark-view-8-hover.png`.
The owning Twin task fixed this in `d37c10f`, with targeted narrow-panel evidence;
the lead must include that dependency correction in the independent/integrated
review. The Home screenshots retain the pre-dependency-fix state honestly.
This builder handoff is not independent approval.
