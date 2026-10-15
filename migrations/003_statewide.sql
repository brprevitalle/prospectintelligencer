CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE TABLE map_datasets (
 id uuid PRIMARY KEY, fingerprint text NOT NULL UNIQUE, state text NOT NULL DEFAULT 'loading',
 created_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz,
 expected_towns integer NOT NULL DEFAULT 351, manifest jsonb NOT NULL
);
CREATE TABLE map_towns (
 dataset_id uuid NOT NULL REFERENCES map_datasets, town_id integer NOT NULL, name text NOT NULL,
 fiscal_year integer, state text NOT NULL DEFAULT 'pending', error text,
 parcel_count integer NOT NULL DEFAULT 0, assessment_count integer NOT NULL DEFAULT 0,
 other_count integer NOT NULL DEFAULT 0, quarantine_count integer NOT NULL DEFAULT 0,
 source jsonb NOT NULL, boundary geometry(Geometry,4326), stats jsonb NOT NULL DEFAULT '{}',
 PRIMARY KEY(dataset_id,town_id)
);
CREATE TABLE map_parcels (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 dataset_id uuid NOT NULL, town_id integer NOT NULL, source_fid bigint NOT NULL,
 loc_id text, map_par_id text, segment text NOT NULL, assessment_count integer NOT NULL,
 issues text[] NOT NULL, raw jsonb NOT NULL, geom geometry(Geometry,3857),
 FOREIGN KEY(dataset_id,town_id) REFERENCES map_towns,
 UNIQUE(dataset_id,town_id,source_fid)
);
CREATE INDEX map_parcels_geom ON map_parcels USING gist(geom);
CREATE INDEX map_parcels_lookup ON map_parcels(dataset_id,town_id,loc_id);
CREATE INDEX map_parcels_segment ON map_parcels(dataset_id,town_id,segment);
CREATE TABLE map_assessments (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 dataset_id uuid NOT NULL, town_id integer NOT NULL, source_fid bigint NOT NULL,
 loc_id text, prop_id text, address text, owner_name text, owner_mail text,
 segment text NOT NULL, issues text[] NOT NULL, raw jsonb NOT NULL,
 FOREIGN KEY(dataset_id,town_id) REFERENCES map_towns,
 UNIQUE(dataset_id,town_id,source_fid)
);
CREATE INDEX map_assessments_lookup ON map_assessments(dataset_id,town_id,loc_id);
CREATE INDEX map_assessments_address ON map_assessments USING gin(address gin_trgm_ops);
CREATE INDEX map_assessments_owner ON map_assessments USING gin(owner_name gin_trgm_ops);
CREATE TABLE map_supplementary (
 dataset_id uuid NOT NULL, town_id integer NOT NULL, layer text NOT NULL, source_fid bigint NOT NULL,
 raw jsonb NOT NULL, geom geometry(Geometry,3857),
 FOREIGN KEY(dataset_id,town_id) REFERENCES map_towns,
 PRIMARY KEY(dataset_id,town_id,layer,source_fid)
);
