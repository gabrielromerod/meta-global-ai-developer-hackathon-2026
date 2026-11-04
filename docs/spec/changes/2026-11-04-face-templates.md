# Spec change: Nov 4, 2026, opt-in local face templates for recurring visitors

Applies to [`docs/spec/vigil-spec.md`](../vigil-spec.md). Owner decision of Nov 4 (QA audit,
item 2, "a recurring visitor seen for the 4th time"). The owner chose **face templates**,
accepted the legal-risk note below, and chose **"Give it a name"** as the only owner action
that adds meaning to a profile.

This narrows the Nov 2 claim. The old claim was "Vigil does not identify anyone and creates no
face, voice or body templates". The new claim: **rules, roles and stories never use a face,
voice or body template.** Faces only label an owner-facing profile card.

## What changes

| Block | Before | After |
| --- | --- | --- |
| NFR-003 | Vigil creates no face, voice or body templates | The person schemas (appearance, track, subject, event, position) still have no face or name fields. Opt-in face templates live in a separate store, `data/faces.db`, are computed on the home box, are never sent to a model API, and are enrolled only from people inside the property |
| FR-044 | Roles from spatial origin only | Unchanged. A face-profile match never sets, changes or overrides `actor_role`, and a named profile is never treated as household because of its name |
| FR-021 draft card | "...it does not identify anyone and creates no face, voice or body templates" | "...rules and roles never use a face, voice or body template". The named-person notice now starts "Rules can't recognise individuals" |
| Validator check 7 | Names fail | Unchanged. A profile name never reaches the ledger, Wonder or a story |

## How it works

- **Opt-in.** Nothing is enrolled or listed unless `VIGIL_FACE_TEMPLATES=1`. The off state is the
  default and is tested (`test_faces_off_by_default_lists_nothing`).
- **Local models.** OpenCV's YuNet detector and SFace recogniser are already in
  `opencv-python-headless`; no new dependency. The two ONNX files go in `data/models/`
  (gitignored): `face_detection_yunet_2023mar.onnx` and `face_recognition_sface_2021dec.onnx`,
  both from the opencv_zoo project. Without them, enrolment stops with `FacesUnavailable` and
  the card says the models are not installed.
- **Inside the property only.** `vigil/faces/enroll.py` samples a person track only on frames
  whose foot point lies in a property zone (`interior_yard` or `egress`). Frames in a
  `perimeter` zone (the street strip) or outside every zone are never read. When zones overlap,
  `perimeter` wins.
- **Matching.** Each track's best 5 faces, each at least 24 px wide, are averaged. The average
  joins the nearest profile when the cosine similarity is ≥ 0.363 (SFace's published threshold);
  otherwise it starts a new profile. One capture adds at most one sighting per profile.
- **Owner actions.** Reads are LAN-only. Name, flag, merge and forget are owner-only
  (`require_owner`). Crops are served with `cache-control: no-store`.
- **Retention.** `scripts/faces_enroll.py` purges faces older than `VIGIL_FACE_RETENTION_DAYS`
  (default 30) before each run. "Forget" deletes the profile and all its faces at once.

## Fallback: clothing signature (owner decision, Nov 4)

On the 180° Duo panoramas YuNet found no usable face: in the first run on 3 captures it read
120 frames from 10 person tracks and kept 0 faces. So the profile card falls back to
`vigil/faces/appearance.py`. Person tracks inside the property are grouped across processed
captures by Muse Spark's FR-009 allowlist notes only: upper colour, lower colour and carried
items. At least two traits must be known, so "unknown/unknown" never groups. Clips that start
within 2 minutes of each other count as one arrival, so two cameras on one visit count once.
Merged `moment-*` results are skipped, because their source clips are already counted. The
thumbnails are upper-body crops from the capture's masked video parts. The card says "Matched
by clothing (…), not by face. People dressed alike are grouped together." The owner can name a
clothing profile (`data/appearance/names.json`). Tests: `tests/unit/test_appearance_profiles.py` (5).

## Honest limits

- The Duo panoramas are 180° at 1536 px wide (sub stream), so a face at garden distance is
  often 10–20 px wide and is skipped, not guessed. The doorbell is the realistic source of
  usable faces; no doorbell capture has been processed yet.
- No accuracy target is pre-registered. Until a labelled set exists, "Seen 4 times" is a count
  of matched sightings, not a measured identification rate.

## Legal-risk note (accepted by the owner, Nov 4)

Face templates are biometric data in many places: GDPR Art. 9, Illinois BIPA, Texas CUBI and
Washington's biometric statute, among others. Recording neighbours or passers-by into a template
store can need notice or consent. The design limits exposure as follows:

- it is opt-in;
- the street is never sampled;
- everything stays local;
- retention is short;
- deletion is one tap.

It does not remove the obligation. The public demo video must not show a face crop of anyone
who has not consented.

## Tests

- `tests/unit/test_faces.py` (15): engine filters, the store, matching, merge and purge.
- `tests/unit/test_face_enroll.py` (6): only frames inside the property are read; vehicles and
  people seen only on the street are skipped; overlay boxes are scaled to the video frame; a
  second capture adds a second sighting; tiny faces are counted, not kept.
- `tests/integration/test_faces_api.py` (6): off by default, the recurring count and label,
  LAN-only access, owner-only changes, crop ID validation.
