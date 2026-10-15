from pathlib import Path
from uuid import UUID
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from app.db import connect
from fastapi.staticfiles import StaticFiles
from app.map_api import router as map_router

app = FastAPI(title='LabHaptic Intelligence — Massachusetts', version='0.1.0')
app.include_router(map_router)
app.mount('/static',StaticFiles(directory=Path(__file__).parent/'static'),name='static')
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['localhost', '127.0.0.1', 'testserver'])


@app.get('/', include_in_schema=False)
def index():
    return FileResponse(Path(__file__).parent / 'map.html')


@app.get('/hudson',include_in_schema=False)
def hudson_pilot():
    return FileResponse(Path(__file__).parent / 'index.html')


@app.get('/api/v1/health')
def health():
    with connect() as conn:
        conn.execute('SELECT 1')
    return {'status': 'ok', 'mode': 'local-only'}


def resolve(conn, publication):
    if publication:
        found = conn.execute('SELECT id FROM publications WHERE id=%s AND town_id=141', (publication,)).fetchone()
        if not found:
            raise HTTPException(404, 'Publication not found')
        return found['id']
    row = conn.execute('SELECT active_publication FROM towns WHERE id=141').fetchone()
    if not row or not row['active_publication']:
        raise HTTPException(404, 'No published Hudson data. Run the ingest command first.')
    return row['active_publication']


def filters(publication, q, segment, issue):
    clauses = ['publication_id=%s']
    params = [publication]
    if q:
        clauses.append("(address ILIKE %s OR owner_name ILIKE %s)")
        term = '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        params.extend([term, term])
    if segment:
        clauses.append('segment=%s')
        params.append(segment)
    if issue:
        clauses.append('%s=ANY(issues)')
        params.append(issue)
    return ' AND '.join(clauses), params


@app.get('/api/v1/properties')
def properties(publication: UUID | None = None, q: str = Query('',max_length=150),
               segment: str = Query('',max_length=80), issue: str = Query('',max_length=80),
               limit: int = Query(50,ge=1,le=200), offset: int = Query(0,ge=0,le=100000)):
    with connect() as conn:
        pub = resolve(conn, publication)
        where, params = filters(pub,q,segment,issue)
        counts = conn.execute(f'''SELECT count(*) AS source_records,
            count(DISTINCT parcel_key) AS distinct_parcel_identifiers,
            count(DISTINCT assessment_key) AS distinct_assessment_identifiers
            FROM source_records WHERE {where}''', params).fetchone()
        rows = conn.execute(f'''SELECT source_oid,parcel_key,assessment_key,address,owner_name,owner_mail,
            segment,classification_basis,units,use_code,issues FROM source_records WHERE {where}
            ORDER BY source_oid LIMIT %s OFFSET %s''', [*params,limit,offset]).fetchall()
        return {'publication': str(pub), 'counts': counts, 'records': rows, 'limit':limit,'offset':offset}


@app.get('/api/v1/properties/{source_oid}')
def detail(source_oid: int, publication: UUID):
    with connect() as conn:
        pub = resolve(conn,publication)
        row = conn.execute('''SELECT source_oid,parcel_key,assessment_key,address,owner_name,owner_mail,
            segment,classification_basis,units,use_code,issues,raw,raw_geometry,ST_AsGeoJSON(geom)::json AS geometry
            FROM source_records WHERE publication_id=%s AND source_oid=%s''', (pub,source_oid)).fetchone()
        if not row:
            raise HTTPException(404,'Record not found')
        return {'publication':str(pub),'record':row,'contact_research':'not_started'}


@app.get('/api/v1/summary')
def summary(publication: UUID | None = None):
    with connect() as conn:
        pub = resolve(conn,publication)
        segments = conn.execute('SELECT segment,count(*) AS count FROM source_records WHERE publication_id=%s GROUP BY segment ORDER BY count(*) DESC',(pub,)).fetchall()
        issues = conn.execute('SELECT issue,count(*) AS count FROM source_records,unnest(issues) AS issue WHERE publication_id=%s GROUP BY issue ORDER BY count(*) DESC',(pub,)).fetchall()
        metadata = conn.execute('SELECT * FROM publications WHERE id=%s',(pub,)).fetchone()
        return {'publication':str(pub),'metadata':metadata,'segments':segments,'issues':issues,
                'counting_grain':'source feature rows; not deduplicated properties or assessments',
                'contacts':'not provided by this source; enrichment not started'}


@app.get('/api/v1/owner-candidates')
def owner_candidates(publication: UUID | None = None):
    with connect() as conn:
        pub = resolve(conn,publication)
        rows = conn.execute('''SELECT owner_name,owner_mail,count(DISTINCT parcel_key) AS parcel_count
            FROM source_records WHERE publication_id=%s AND owner_name IS NOT NULL AND owner_mail IS NOT NULL
            AND NOT ('incomplete_owner_mailing_address'=ANY(issues))
            GROUP BY owner_name,owner_mail HAVING count(DISTINCT parcel_key)>1
            ORDER BY count(DISTINCT parcel_key) DESC,owner_name,owner_mail LIMIT 100''',(pub,)).fetchall()
        return {'publication':str(pub),'status':'candidates_only_not_verified_or_merged','records':rows}


@app.get('/api/v1/runs')
def runs():
    with connect() as conn:
        return conn.execute('SELECT id,town_id,state,stage,started_at,finished_at,row_count,error FROM runs ORDER BY started_at DESC LIMIT 50').fetchall()
