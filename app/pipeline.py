import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4
from psycopg.types.json import Jsonb
from app.db import connect
from app.normalize import normalize, PROCESSING_VERSION
from app.source import download, read_snapshot


def publish(conn, run_id, features, manifest):
    town = manifest['town_id']
    if town != 141 or not features or len(features) != manifest['count']:
        raise ValueError('Invalid town or incomplete snapshot')
    ids = [f['properties']['OBJECTID'] for f in features]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate source object IDs')
    if any(f['properties'].get('TOWN_ID') != town for f in features):
        raise ValueError('Wrong-town source record')
    canonical = json.dumps(sorted(features, key=lambda f: f['properties']['OBJECTID']), sort_keys=True)
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    existing = conn.execute('SELECT id FROM publications WHERE town_id=%s AND snapshot_hash=%s AND processing_version=%s',
                            (town, digest, PROCESSING_VERSION)).fetchone()
    if existing:
        # Replaying an old snapshot must not roll the active publication backward.
        return existing['id'], True
    publication = uuid4()
    conn.execute('INSERT INTO publications(id,town_id,run_id,source_url,source_edited_at,snapshot_hash,processing_version,record_count) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                 (publication, town, run_id, manifest['source'], manifest['source_edited_at'], digest, PROCESSING_VERSION, len(features)))
    rows = []
    for feature in features:
        raw = feature['properties']
        row = normalize(raw)
        geometry = feature.get('geometry')
        if not geometry or geometry.get('type') not in ('Polygon', 'MultiPolygon'):
            raise ValueError(f"Missing or unsupported geometry for source object {raw['OBJECTID']}")
        rows.append((publication, raw['OBJECTID'], row['parcel_key'], row['assessment_key'], row['address'],
                     row['owner_name'], row['owner_mail'], row['segment'], row['classification_basis'],
                     row['units'], row['use_code'], Jsonb(raw), row['issues'], json.dumps(geometry), Jsonb(geometry)))
    with conn.cursor() as cur:
        cur.executemany('''INSERT INTO source_records (publication_id,source_oid,parcel_key,assessment_key,address,owner_name,owner_mail,segment,classification_basis,units,use_code,raw,issues,geom,raw_geometry) VALUES
            (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,ST_SetSRID(ST_GeomFromGeoJSON(%s),4326),%s)''', rows)
    invalid = conn.execute('''SELECT count(*) AS n FROM source_records WHERE publication_id=%s
        AND (ST_IsEmpty(geom) OR NOT (ST_XMin(Box3D(geom)) >= -180 AND ST_XMax(Box3D(geom)) <= 180
        AND ST_YMin(Box3D(geom)) >= -90 AND ST_YMax(Box3D(geom)) <= 90))''', (publication,)).fetchone()['n']
    if invalid:
        raise ValueError(f'{invalid} empty or out-of-range geometries; publication blocked')
    conn.execute('''UPDATE source_records SET issues=array_append(issues,'invalid_geometry_quarantined'),geom=NULL
        WHERE publication_id=%s AND NOT ST_IsValid(geom)''', (publication,))
    # Repeated assessment IDs may be legitimate joins; flag rather than merge or sum.
    conn.execute('''UPDATE source_records r SET issues=array_append(issues,'repeated_assessment_identifier')
        WHERE publication_id=%s AND assessment_key IN
        (SELECT assessment_key FROM source_records WHERE publication_id=%s AND assessment_key IS NOT NULL
         GROUP BY assessment_key HAVING count(*)>1)''', (publication, publication))
    conn.execute('UPDATE towns SET active_publication=%s WHERE id=%s', (publication, town))
    return publication, False


def run(snapshot=None):
    run_id = uuid4()
    directory = Path(os.environ.get('DATA_DIR', 'data')) / 'raw' / str(run_id)
    # Session lock covers fetch and publish, but does not keep a database transaction open.
    with connect() as guard:
        guard.autocommit = True
        if not guard.execute('SELECT pg_try_advisory_lock(141001) AS acquired').fetchone()['acquired']:
            raise RuntimeError('A Hudson import is already running')
        with connect() as conn:
            conn.execute("UPDATE runs SET state='failed',stage='interrupted',error='Previous process stopped; rerun from preserved snapshot',finished_at=now() WHERE state='running' AND town_id=141")
            conn.execute("INSERT INTO runs(id,town_id,state,stage,snapshot_path) VALUES (%s,141,'running','fetch',%s)",
                         (run_id, str(snapshot or directory)))
        try:
            features, manifest = read_snapshot(snapshot) if snapshot else download(directory)
            with connect() as conn:
                conn.execute("UPDATE runs SET stage='normalize_validate_publish',row_count=%s WHERE id=%s", (len(features),run_id))
            with connect() as conn:
                publication, reused = publish(conn, run_id, features, manifest)
                conn.execute("UPDATE runs SET state='succeeded',stage=%s,finished_at=now() WHERE id=%s", ('reused' if reused else 'published', run_id))
            return {'run_id': str(run_id), 'publication': str(publication), 'reused': reused, 'source_records': len(features)}
        except Exception as exc:
            with connect() as conn:
                conn.execute("UPDATE runs SET state='failed',stage='failed',error=%s,finished_at=now() WHERE id=%s", (str(exc)[:1000],run_id))
            raise
