-- Vigil SQLite schema (spec 9.3). Times are seconds on the aligned session clock.
CREATE TABLE cameras(id TEXT PRIMARY KEY, name TEXT, width INT, height INT, offset_s REAL);
CREATE TABLE windows(id TEXT PRIMARY KEY, camera_id TEXT, t0 REAL, t1 REAL, path TEXT,
  file_id TEXT, motion REAL, trigger TEXT, status TEXT);
CREATE TABLE camera_ai_events(id TEXT PRIMARY KEY, camera_id TEXT, kind TEXT, t0 REAL, t1 REAL);
CREATE TABLE tracks(id TEXT PRIMARY KEY, camera_id TEXT, cls TEXT, t_first REAL, t_last REAL,
  overlay_path TEXT, origin_zone TEXT);
CREATE TABLE track_windows(track_id TEXT, window_id TEXT, sam_obj_id INT);
CREATE TABLE appearance(track_id TEXT PRIMARY KEY, notes_json TEXT, call_id TEXT);
CREATE TABLE positions(track_id TEXT, t REAL, x REAL, y REAL, z REAL, r95 REAL,
  method TEXT CHECK(method IN ('footpoint','height_prior','fused')), cameras TEXT, flags TEXT);
CREATE TABLE protected_objects(id TEXT PRIMARY KEY, camera_id TEXT, label TEXT, mask_path TEXT,
  bbox_json TEXT, footprint_json TEXT, call_id TEXT, created_at TEXT);
CREATE TABLE watches(id TEXT PRIMARY KEY, camera_id TEXT, phrase TEXT, origin TEXT, status TEXT,
  expires_at TEXT, source_visit_id TEXT, reason TEXT);
CREATE TABLE events(id TEXT PRIMARY KEY, visit_id TEXT, camera_id TEXT, track_id TEXT, type TEXT,
  t0 REAL, t1 REAL, target TEXT, clip_t0 REAL, clip_t1 REAL, subject_id TEXT,
  actor_role TEXT);
CREATE TABLE visits(id TEXT PRIMARY KEY, scenario TEXT, t0 REAL, t1 REAL, state TEXT, floor TEXT,
  proposal TEXT, verdict TEXT, escalated INT, story_json TEXT);
CREATE TABLE gaps(id TEXT PRIMARY KEY, visit_id TEXT, kind TEXT, t0 REAL, t1 REAL,
  from_camera TEXT, to_camera TEXT, region_id TEXT, resolved INT);
CREATE TABLE rules(id TEXT PRIMARY KEY, json TEXT, applies_to TEXT
  CHECK(applies_to IN ('anyone','external_visitor_only','non_household')), source TEXT, state TEXT,
  created_at TEXT);
CREATE TABLE rule_hits(rule_id TEXT, visit_id TEXT, event_id TEXT);
CREATE TABLE model_calls(id TEXT PRIMARY KEY, model TEXT, purpose TEXT, visit_id TEXT, req_hash TEXT,
  latency_ms INT, in_tokens INT, out_tokens INT, units REAL, cost_usd REAL, cached INT, ok INT,
  error TEXT, backend TEXT, gpu_s REAL, feature TEXT, funding TEXT, created_at TEXT);  -- backend, gpu_s: FR-042; feature: spec 11.4
CREATE TABLE validations(visit_id TEXT, attempt INT, passed INT, failures_json TEXT);

-- Added during integration (2026-11-02), beyond spec 9.3:
CREATE TABLE visit_tracks(visit_id TEXT, track_id TEXT, PRIMARY KEY (visit_id, track_id));
CREATE TABLE triage(visit_id TEXT PRIMARY KEY, escalate INT, forced INT, source TEXT, reason TEXT,
  call_id TEXT);
CREATE TABLE drafts(visit_id TEXT, attempt INT, call_id TEXT, draft_json TEXT,
  PRIMARY KEY (visit_id, attempt));
CREATE TABLE outages(camera_id TEXT, t0 REAL, t1 REAL, attempts INT);
-- Added for the Nov 2 spec corrections (FR-029, FR-044):
CREATE TABLE subjects(id TEXT PRIMARY KEY, visit_id TEXT, track_ids_json TEXT, actor_role TEXT
  CHECK(actor_role IN ('household_insider','expected_visitor','external_visitor','unknown')),
  role_basis TEXT);
CREATE TABLE expected_windows(id TEXT PRIMARY KEY, label TEXT, starts_at TEXT, ends_at TEXT,
  cameras_json TEXT, zones_json TEXT,
  state TEXT CHECK(state IN ('scheduled','active','expired','cancelled')), created_at TEXT);
CREATE TABLE checkins(id TEXT PRIMARY KEY, session_id TEXT, starts_at TEXT, expires_at TEXT,
  bound_subject TEXT, revoked INT);
CREATE TABLE feedback(visit_id TEXT, kind TEXT, created_at TEXT);
