"""Standalone Overture acquisition benchmark; reads town boundary, changes no API/data."""
import json
import time
import resource
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen
import io
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import duckdb
import pyarrow.parquet as pq
from shapely.geometry import shape
from app.db import connect

started = time.perf_counter()
stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
out = Path('data/overture/hudson') / stamp
out.mkdir(parents=True)
report = {'started_at': stamp, 'town': 'Hudson, Massachusetts', 'town_id': 141,
          'method': 'STAC file selection, bounding-box predicate, exact town-boundary intersection; original geometries retained, not clipped',
          'layers': [], 'duckdb_version': duckdb.__version__, 'threads': 2, 'memory_limit': '1GB'}
def save():
    (out/'report.json').write_text(json.dumps(report, indent=2))
with connect() as pg:
    pg.execute('SET TRANSACTION READ ONLY')
    row = pg.execute("""SELECT t.dataset_id, ST_AsGeoJSON(boundary) AS geometry
      FROM map_towns t JOIN map_datasets d ON d.id=t.dataset_id
      WHERE town_id=141 AND t.state='ready' AND d.state='ready'
      ORDER BY d.created_at DESC LIMIT 1""").fetchone()
    if not row or not row['geometry']:
        raise RuntimeError('Ready Hudson boundary required')
boundary = json.loads(row['geometry'])
(out/'boundary.geojson').write_text(json.dumps(boundary))
bbox = shape(boundary).bounds
report.update(boundary_dataset_id=str(row['dataset_id']), bbox=bbox)
with urlopen('https://stac.overturemaps.org/catalog.json', timeout=60) as r:
    catalog = json.load(r)
release = catalog['latest']
report['release'] = release
(out/'catalog.json').write_text(json.dumps(catalog, indent=2))
with urlopen(f'https://stac.overturemaps.org/{release}/collections.parquet', timeout=120) as r:
    index_bytes = r.read()
(out/'collections.parquet').write_bytes(index_bytes)
index = pq.read_table(io.BytesIO(index_bytes)).to_pylist()
db = duckdb.connect(str(out/'hudson.duckdb'))
db.execute("SET threads=2; SET memory_limit='1GB'")
db.execute("SET extension_directory='/tmp/prospect-duckdb-extensions'")
for ext in ['httpfs', 'spatial']:
    db.execute(f'INSTALL {ext}; LOAD {ext}')
db.execute("SET s3_region='us-west-2'")
db.execute("CREATE TABLE boundary AS SELECT ST_GeomFromGeoJSON(?) geometry", [json.dumps(boundary)])
report['setup_seconds'] = round(time.perf_counter()-started, 3)
types = ['building','building_part','place','address','segment','connector','infrastructure','land','land_cover','land_use','water','bathymetry','division','division_area','division_boundary']
def lit(v):
    return "'" + str(v).replace("'", "''") + "'"
for kind in types:
    t = time.perf_counter()
    result = {'type':kind}
    paths=[]
    for item in index:
        b=item.get('bbox')
        if item.get('collection')!=kind or item.get('type')!='Feature' or not b: continue
        if b['xmin']<=bbox[2] and b['xmax']>=bbox[0] and b['ymin']<=bbox[3] and b['ymax']>=bbox[1]:
            paths.append(item['assets']['aws']['alternate']['s3']['href'])
    result['source_files_selected']=len(paths)
    print(f'{kind}: scanning {len(paths)} source files', flush=True)
    try:
        if paths:
            files='['+','.join(lit(p) for p in paths)+']'
            db.execute(f"""CREATE TABLE "{kind}" AS SELECT * FROM read_parquet({files}, hive_partitioning=false)
              WHERE bbox.xmin <= {bbox[2]} AND bbox.xmax >= {bbox[0]}
                AND bbox.ymin <= {bbox[3]} AND bbox.ymax >= {bbox[1]}
                AND ST_Intersects(geometry, (SELECT geometry FROM boundary))""")
            file=out/f'{kind}.parquet'
            db.execute(f'COPY "{kind}" TO {lit(file)} (FORMAT PARQUET, COMPRESSION ZSTD)')
            result.update(rows=db.execute(f'SELECT count(*) FROM "{kind}"').fetchone()[0], bytes=file.stat().st_size,
                          unique_ids=db.execute(f'SELECT count(DISTINCT id) FROM "{kind}"').fetchone()[0])
        else:
            result.update(rows=0, bytes=0, unique_ids=0)
        result['status']='complete'
    except Exception as e:
        result.update(status='failed', error=str(e))
    result['seconds']=round(time.perf_counter()-t,3)
    report['layers'].append(result)
    save()
    print(json.dumps(result),flush=True)
db.execute('CHECKPOINT')
db.close()
report.update(total_seconds=round(time.perf_counter()-started,3),
              total_rows=sum(x.get('rows',0) for x in report['layers']),
              parquet_bytes=sum(x.get('bytes',0) for x in report['layers']),
              database_bytes=(out/'hudson.duckdb').stat().st_size,
              peak_process_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
              status='complete' if all(x['status']=='complete' for x in report['layers']) else 'partial',
              network_bytes='not measured; local output size is not network transfer size')
save()
print('REPORT '+str(out/'report.json'),flush=True)
print(json.dumps(report,indent=2),flush=True)
