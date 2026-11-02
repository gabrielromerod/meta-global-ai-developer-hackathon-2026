-- Vigil SQLite schema (spec 9.3). Times are seconds on the aligned session clock.
CREATE TABLE cameras(id TEXT PRIMARY KEY, name TEXT, width INT, height INT, offset_s REAL);
CREATE TABLE windows(id TEXT PRIMARY KEY, camera_id TEXT, t0 REAL, t1 REAL, path TEXT,
  file_id TEXT, motion REAL, trigger TEXT, status TEXT);
CREATE TABLE camera_ai_events(id TEXT PRIMARY KEY, camera_id TEXT, kind TEXT, t0 REAL, t1 REAL);
CREATE TABLE tracks(id TEXT PRIMARY KEY, camera_id TEXT, cls TEXT, t_first REAL, t_last REAL,
  overlay_path TEXT);
CREATE TABLE track_windows(track_id TEXT, window_id TEXT, sam_obj_id INT);
CREATE TABLE appearance(track_id TEXT PRIMARY KEY, notes_json TEXT, call_id TEXT);
CREATE TABLE positions(track_id TEXT, t REAL, x REAL, y REAL, z REAL, r95 REAL,
  method TEXT CHECK(method IN ('footpoint','height_prior','fused')), cameras TEXT, flags TEXT);
CREATE TABLE protected_objects(id TEXT PRIMARY KEY, camera_id TEXT, label TEXT, mask_path TEXT,
  bbox_json TEXT, footprint_json TEXT, call_id TEXT, created_at TEXT);
CREATE TABLE watches(id TEXT PRIMARY KEY, camera_id TEXT, phrase TEXT, origin TEXT, status TEXT,
  expires_at TEXT, source_visit_id TEXT, reason TEXT);
CREATE TABLE events(id TEXT PRIMARY KEY, visit_id TEXT, camera_id TEXT, track_id TEXT, type TEXT,
  t0 REAL, t1 REAL, target TEXT, clip_t0 REAL, clip_t1 REAL);
CREATE TABLE visits(id TEXT PRIMARY KEY, scenario TEXT, t0 REAL, t1 REAL, state TEXT, floor TEXT,
  proposal TEXT, verdict TEXT, escalated INT, story_json TEXT);
CREATE TABLE gaps(id TEXT PRIMARY KEY, visit_id TEXT, kind TEXT, t0 REAL, t1 REAL,
  from_camera TEXT, to_camera TEXT, region_id TEXT, resolved INT);
CREATE TABLE rules(id TEXT PRIMARY KEY, json TEXT, source TEXT, state TEXT, created_at TEXT);
CREATE TABLE rule_hits(rule_id TEXT, visit_id TEXT, event_id TEXT);
CREATE TABLE model_calls(id TEXT PRIMARY KEY, model TEXT, purpose TEXT, visit_id TEXT, req_hash TEXT,
  latency_ms INT, in_tokens INT, out_tokens INT, units REAL, cost_usd REAL, cached INT, ok INT,
  error TEXT, backend TEXT, gpu_s REAL, created_at TEXT);  -- backend, gpu_s: FR-042
CREATE TABLE validations(visit_id TEXT, attempt INT, passed INT, failures_json TEXT);
