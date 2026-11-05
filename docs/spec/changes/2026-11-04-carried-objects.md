# Spec change: Nov 4, 2026, possible knife or gun carried onto the property (FR-045)

Applies to [`docs/spec/vigil-spec.md`](../vigil-spec.md). Owner decision of Nov 4: SAM 3.1 also
looks for a knife or a gun; when one is held by someone who is not household, Vigil raises an
alert, and Muse Wonder writes the cited story. The owner chose, in this order:

1. **A rule raises the alert, not Wonder.** The verdict invariant is unchanged: only a rule can
   produce `needs_attention`; Wonder can raise normal to noteworthy and never lower anything.
2. **Arrival and check-in decide who is household, not faces.** Roles stay spatial (FR-044). A
   person who walks in from the street with no check-in is non-household (and `unknown` fails
   closed), so a carried knife alerts. A person who came out of the house, or checked in with
   "I'm outside", is household, so a kitchen knife in their hand does not alert. A covered face
   changes nothing, because faces never decide anything.

## What changes

| Block | Change |
| --- | --- |
| FR-006 phrases | Every active window asks SAM 3.1 for `person`, `car` **and** `knife`, `gun` (`CARRIED_OBJECTS` in `vigil/perception/events.py`). Cost: SAM calls per window go from 2 to 4 ($0.02 each); a typical event clip goes from about $0.15–0.25 to about $0.35–0.45 |
| FR-008 events | New event type `carry`: a listed object's box centre sits on a tracked person's box (with arm's reach, 30% of the box width) in at least 2 frames; one event per held span, on the **person's** track, `target` = the object phrase. Geometry only: no model decides what is held |
| FR-012 rules | New default rule `r_carried_object`, "Possible knife or gun carried by a non-household person": target `carried_object` `*`, trigger `carry`, always active, `needs_attention`, `applies_to: non_household` |
| FR-014/015 story | Template: "… was holding an object marked as a possible knife on the … camera at …". Wonder's prompt (v4) explains `carry` events and must hedge ("possible"). Validator check 5 now also rejects `weapon`, `weapons`, `armed` (with `dangerous` and `threat` already banned): the alert comes from the rule, the story describes |
| UI | The clip inspector shows a red alert with the rule name and "SAM 3.1 marked a possible knife at 0:12"; the bell lists real clips whose rule raised `needs_attention` (real-only home box) and opens the clip |
| Models | `EventType` and `RuleTrigger` gain `carry`; `TargetKind` gains `carried_object` (`vigil/models.py`, integrator-owned, changed on the owner's request) |

## Honest limits

- No accuracy is claimed. Nothing labelled has measured how often SAM 3.1 finds a knife at
  garden distance on the 180° Duo panoramas, where a hand-held knife can be 10–25 px long. A
  missed knife means no alert, so the demo must not imply coverage it has not measured.
- "Immediately" means as soon as the clip is processed (`vigil process --cloud`), about one to
  three minutes after the clip ends. Automatic processing of each new clip is not wired, because
  every run is a paid call that needs the owner's budget approval.
- A held phone, tool or umbrella can be marked as a knife or gun. The alert says "possible" and
  links the clip for the owner to check.

## Tests

`tests/unit/test_carried_objects.py` (17): both phrases asked on every window; carry event on the
person; no event far away, for one frame, or for unlisted objects; the rule fires for external,
expected and unknown roles and not for household; Wonder cannot lower it; hedged template passes
the validator; the story may not say weapon, armed, dangerous or threat.
`tests/integration/test_captures_api.py`: `test_real_only_bell_lists_clips_whose_rule_raised_an_alert`,
`test_capture_analysis_names_the_rule_and_the_carried_object`. `web-next/src/app/captures.test.tsx`:
"shows which rule raised the alert and the object SAM marked, never a face match".

## Field result and zoomed crops (Nov 4, evening)

Real walk with a knife, filmed on the owner's cameras. The blade is visible to a person in the
Front left clip. SAM 3.1 found no knife on the full frame in any of the 6 clips processed. On a
2.75x crop of the main-stream part of that clip it found the blade in 9 consecutive frames at
0.82 confidence. On a 3x crop of the sub-stream part it found nothing, and "kitchen knife" found
nothing on either crop. That is one positive result, not an accuracy figure.

`vigil/perception/zoom.py` now plans up to 3 crops per window from SAM's person boxes, and
`vigil/cloud.py` asks for knife and gun on those crops only. A window with no person makes no
carried-object call. Each crop is masked again and passes the upload guard with the polygons
shifted into crop pixels. Boxes map back to the full frame, so events, rules and the verdict do
not change. SAM calls for carried objects are now 2 per crop instead of 2 per window.
