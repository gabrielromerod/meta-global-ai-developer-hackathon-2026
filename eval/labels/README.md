# Evaluation labels (pre-registered)

These files are the ground truth for `vigil eval` (FR-024, NFR-023). **They are written
and committed before any pipeline run on the footage they describe.** That ordering is
the point: the commit date of each label file must be earlier than the commit that adds
`eval/results.json`, so nobody can tune the labels to the results. `vigil eval` records
the SHA-256 of every label file in `eval/results.json` (`labels_sha256`), which ties each
result to the exact label commit.

Workflow (task T-07, then T-27):

1. Film the scenario (consenting adults only; plates covered; privacy polygons on).
2. Watch the raw clips and write `eval/labels/<scenario>.json` from
   [`_template.json`](./_template.json). Do not run perception or the pipeline first.
3. Commit the label file on its own (`eval: pre-register labels for scenario X`).
4. Only then run `vigil process` and `vigil eval`. Never edit a label after its run. If a
   label turns out to be wrong, add a new commit that says so, and report both numbers.

## Schema (`schema_version: 1`)

Files whose name starts with `_` are ignored. Keys starting with `$` are comments.
Times are seconds on the aligned session clock (spec 9.3).

| Field | Type | Meaning |
| --- | --- | --- |
| `scenario` | string | Scenario id (`A`, `B`, `C`, ...); one file per scenario |
| `title` | string | What happens, in neutral words |
| `session` | string | Recording session the times refer to |
| `lighting` | `day`, `dusk`, `night_ir`, `unknown` | Night IR results are reported separately (spec 13.3) |
| `expected_verdict` | `normal`, `noteworthy`, `needs_attention`, `cant_confirm` | The most severe verdict any visit in the scenario should get |
| `expected_escalated` | bool or null | Whether triage should escalate (FR-013) |
| `subjects[]` | `{id, class, appearances[]}` | Each person or vehicle, by anonymous id (`S1`, `V1`); `class` is person, vehicle, package or object |
| `subjects[].appearances[]` | `{camera_id, t0, t1}` | Each interval the subject is visible on a camera |
| `gaps[]` | `{id, kind, t0, t1, region_id}` | Intervals with the subject out of every view (FR-011); kind is blind_spot, ambiguous_link or outage |
| `events[]` | `{type, camera_id, t, target}` | Labelled events (enter, exit, cross, touch, removed, dwell) |
| `rules_fired` | list of rule ids | Rules that should fire |
| `labelled_by` | string | A team **role**, never a name |
| `labelled_at` | ISO-8601 | When the label was written |

**No identity fields exist** (NFR-003): no names, faces, ages, genders, skin tone or
ethnicity. Subjects are anonymous ids; the label says what happened, never who.

## Pipeline results consumed by `vigil eval`

`vigil eval` reads one JSON per scenario from `eval/outputs/<scenario>.json` (or a single
file with `{"scenarios": [...]}`):

```json
{"scenario": "C", "motion_triggers": 10,
 "visits": [{"id": "v3", "t0": 0, "t1": 95, "verdict": "needs_attention",
             "escalated": true, "forced": true,
             "story": [{"text": "...", "event_ids": ["e17"], "source": "wonder", "gap_id": null}],
             "events": [{"id": "e17", "camera_id": "side_left", "t0": 21.5, "t1": 22.5}],
             "gaps": [{"id": "g4", "kind": "blind_spot", "t0": 40.3, "t1": 81.2}],
             "links": [{"from": {"camera_id": "front", "t0": 1, "t1": 9},
                        "to": {"camera_id": "side_left", "t0": 15, "t1": 39}}],
             "positions": [{"t": 30.0}]}],
 "camera_ai_events": [{"camera_id": "side_left", "kind": "person", "t0": 14, "t1": 30}],
 "tracks": [{"camera_id": "side_left", "cls": "person", "t_first": 15, "t_last": 39}]}
```

## Metric definitions (fixed before the run)

| Metric | Definition | Target (NFR-023) |
| --- | --- | --- |
| Alert reduction | 1 - alerts / motion triggers; an alert is a visit with verdict `needs_attention` | at least 80% |
| Correct verdicts | Scenarios whose most severe visit verdict equals `expected_verdict`; a missing result counts as wrong | at least 10 of 12 |
| Link precision | Share of system links whose two ends overlap the same labelled subject | at least 90% |
| Claims inside gaps | Non-gap sentences citing an event that overlaps a gap's interior by more than 0.5 s | 0 |
| Uncited sentences shipped | Sentences with neither event ids nor a gap id | 0 |
| Escalation rate | Escalated visits / visits (FR-013) | reported |
| Positions inside gaps | 3D positions with a time strictly inside a gap (FR-039) | 0, reported |
| Gaps matched | Labelled gaps with a system gap whose start and end are each within 1 s (FR-011) | reported |
| Reolink/SAM agreement | Reolink person events overlapped by a SAM person track on the same camera (spec 6) | reported |

Misses are published, never dropped.
