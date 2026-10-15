CREATE EXTENSION IF NOT EXISTS postgis;
CREATE TABLE towns (
  id integer PRIMARY KEY, name text NOT NULL,
  active_publication uuid
);
INSERT INTO towns(id,name) VALUES (141,'Hudson');
CREATE TABLE runs (
  id uuid PRIMARY KEY, town_id integer NOT NULL REFERENCES towns,
  state text NOT NULL CHECK(state IN ('running','succeeded','failed')),
  stage text NOT NULL, started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz, error text, snapshot_path text,
  row_count integer NOT NULL DEFAULT 0
);
CREATE TABLE publications (
  id uuid PRIMARY KEY, town_id integer NOT NULL REFERENCES towns,
  run_id uuid NOT NULL REFERENCES runs,
  source_url text NOT NULL, source_edited_at bigint NOT NULL,
  snapshot_hash text NOT NULL, processing_version text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(), record_count integer NOT NULL,
  UNIQUE(town_id,snapshot_hash,processing_version)
);
ALTER TABLE towns ADD FOREIGN KEY(active_publication) REFERENCES publications;
-- Source features are retained at source grain. They are NOT unique assessment rows.
CREATE TABLE source_records (
  publication_id uuid NOT NULL REFERENCES publications,
  source_oid bigint NOT NULL,
  parcel_key text, assessment_key text,
  address text, owner_name text, owner_mail text,
  segment text NOT NULL, classification_basis text NOT NULL,
  units integer, use_code text, raw jsonb NOT NULL,
  issues text[] NOT NULL,
  geom geometry(Geometry,4326) NOT NULL,
  PRIMARY KEY(publication_id,source_oid)
);
CREATE INDEX source_records_geom ON source_records USING gist(geom);
CREATE INDEX source_records_segment ON source_records(publication_id,segment);
CREATE INDEX source_records_owner ON source_records(publication_id,owner_name,owner_mail);
CREATE INDEX source_records_issues ON source_records USING gin(issues);
-- Human research is deliberately outside replaceable publications.
CREATE TABLE property_notes (
  town_id integer NOT NULL REFERENCES towns,
  parcel_key text NOT NULL, note text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(town_id,parcel_key)
);
