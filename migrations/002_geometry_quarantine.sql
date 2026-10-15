-- Keep original geometry even when it is unsuitable for rendering or spatial analysis.
ALTER TABLE source_records ADD COLUMN raw_geometry jsonb;
UPDATE source_records SET raw_geometry=ST_AsGeoJSON(geom)::jsonb;
ALTER TABLE source_records ALTER COLUMN raw_geometry SET NOT NULL;
ALTER TABLE source_records ALTER COLUMN geom DROP NOT NULL;
