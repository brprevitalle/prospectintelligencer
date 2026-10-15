import os
from uuid import uuid4
import pytest
from contextlib import contextmanager
from psycopg.types.json import Jsonb
from fastapi.testclient import TestClient
from test_integration import conn
from app import map_api
from app.api import app

pytestmark=pytest.mark.skipif(not os.environ.get("DATABASE_URL"),reason="PostGIS DATABASE_URL required")


@pytest.fixture
def map_data(conn,monkeypatch):
    dataset=uuid4()
    conn.execute("INSERT INTO map_datasets(id,fingerprint,state,manifest) VALUES (%s,%s,'ready','{}')",(dataset,str(dataset)))
    conn.execute("INSERT INTO map_towns(dataset_id,town_id,name,state,parcel_count,assessment_count,source,boundary) VALUES (%s,141,'Hudson','ready',1,2,'{}',ST_MakeEnvelope(-71.6,42.3,-71.5,42.4,4326))",(dataset,))
    geom="ST_Transform(ST_MakeEnvelope(-71.57,42.39,-71.569,42.391,4326),3857)"
    parcel=conn.execute(f"INSERT INTO map_parcels(dataset_id,town_id,source_fid,loc_id,segment,assessment_count,issues,raw,geom) VALUES (%s,141,1,'A','multiple_uses',2,'{{}}','{{}}',{geom}) RETURNING id",(dataset,)).fetchone()['id']
    for fid,segment in [(1,'single_family'),(2,'commercial_unclassified')]:
        conn.execute("INSERT INTO map_assessments(dataset_id,town_id,source_fid,loc_id,prop_id,address,owner_name,segment,issues,raw) VALUES (%s,141,%s,'A',%s,'1 MAIN ST','TEST LLC',%s,'{}',%s)",(dataset,fid,str(fid),segment,Jsonb({'FY':2026,'TOTAL_VAL':100})))
    conn.commit()
    @contextmanager
    def connection():yield conn
    monkeypatch.setattr(map_api,'connect',connection)
    map_api.tile_data.cache_clear()
    return TestClient(app),dataset,parcel


def test_catalog_preserves_parcel_assessment_grains(map_data):
    client,dataset,parcel=map_data
    d=client.get('/api/v1/map/catalog').json()
    assert d['totals']['parcels']==1
    assert d['totals']['assessments']==2
    response=client.get(f'/api/v1/map/{dataset}/parcels/{parcel}').json()
    assert len(response['assessments'])==2
    assert response['parcel']['assessment_count']==2


def test_map_filter_agrees_with_parcel_classification(map_data):
    client,dataset,_=map_data
    assert client.get(f'/api/v1/map/{dataset}/search?segment=single_family').json()['records']==[]
    assert len(client.get(f'/api/v1/map/{dataset}/search?segment=multiple_uses').json()['records'])==2
    assert client.get(f'/api/v1/map/{dataset}/search?q=%25%25%25').json()['records']==[]
    assert client.get(f'/api/v1/map/{dataset}/search?q=ab').status_code==422
    assert client.get(f'/api/v1/map/{dataset}/search?q=TEST').status_code==200
    assert client.get(f'/api/v1/map/{uuid4()}/search').status_code==404


def test_vector_tiles_have_valid_bounds_and_filtered_payload(map_data):
    import math
    client,dataset,_=map_data
    z=16;x=int((-71.5695+180)/360*2**z);y=int((1-math.asinh(math.tan(math.radians(42.3905)))/math.pi)/2*2**z)
    r=client.get(f'/api/v1/map/{dataset}/tiles/{z}/{x}/{y}.mvt')
    assert r.status_code==200 and len(r.content)>0
    assert r.headers['content-type']=='application/vnd.mapbox-vector-tile'
    assert client.get(f'/api/v1/map/{dataset}/tiles/{z}/{x}/{y}.mvt?segment=single_family').content==b''
    assert client.get(f'/api/v1/map/{dataset}/tiles/99/0/0.mvt').status_code==422
    assert client.get(f'/api/v1/map/{dataset}/tiles/13/99999/0.mvt').status_code==422
    assert client.get(f'/api/v1/map/{dataset}/tiles/8/1/1.mvt').content==b''


def test_detail_and_neighbors_are_dataset_scoped(map_data):
    client,dataset,parcel=map_data
    assert client.get(f'/api/v1/map/{uuid4()}/parcels/{parcel}').status_code==404
    assert client.get(f'/api/v1/map/{dataset}/parcels/{parcel}/abutters').json()['records']==[]
    assert client.get(f'/api/v1/map/{dataset}/parcels/99999999').status_code==404


def test_geometry_quarantine_preserves_original_archive_boundary():
    import shapely
    from app.statewide import geometry_values
    bad=shapely.Polygon([(0,0),(1,1),(1,0),(0,1),(0,0)])
    rows=[{'SHAPE':shapely.to_wkb(bad),'OBJECTID':1}]
    values,reasons=geometry_values({'geometry_name':'SHAPE','crs':'EPSG:26986'},rows)
    assert values==[None]
    assert 'Self-intersection' in reasons[0]


def test_supporting_view_includes_tabular_records_and_excludes_parcels(map_data,conn):
    import math
    client,dataset,_=map_data
    conn.execute("INSERT INTO map_supplementary VALUES (%s,141,'M141OthLeg',7,%s,ST_Transform(ST_MakeEnvelope(-71.57,42.39,-71.569,42.391,4326),3857))",(dataset,Jsonb({'MAP_PAR_ID':'LEGAL-7','LEGAL_TYPE':'EASEMENT'})))
    conn.execute("INSERT INTO map_supplementary VALUES (%s,141,'M141_LUT',7,%s,NULL)",(dataset,Jsonb({'CODE':'EASEMENT','CODE_DESC':'Right of access'})))
    conn.commit()
    rows=client.get(f'/api/v1/map/{dataset}/supporting?town=141').json()['records']
    assert len(rows)==2 and all('assessment_id' not in r for r in rows)
    assert sum(r['lng'] is None for r in rows)==1
    assert client.get(f'/api/v1/map/{dataset}/supporting?town=140').json()['records']==[]
    assert len(client.get(f'/api/v1/map/{dataset}/supporting?q=Right').json()['records'])==1
    detail=client.get(f'/api/v1/map/{dataset}/supporting/141/M141_LUT/7').json()['record']
    assert detail['geometry'] is None and detail['raw']['CODE']=='EASEMENT'
    assert client.get(f'/api/v1/map/{uuid4()}/supporting/141/M141_LUT/7').status_code==404
    assert client.get(f'/api/v1/map/{dataset}/supporting/140/M141_LUT/7').status_code==404
    z=16;x=int((-71.5695+180)/360*2**z);y=int((1-math.asinh(math.tan(math.radians(42.3905)))/math.pi)/2*2**z)
    tile=client.get(f'/api/v1/map/{dataset}/tiles/{z}/{x}/{y}.mvt?records=supporting')
    assert tile.status_code==200 and b'M141OthLeg' in tile.content
    assert b'M141_LUT' not in tile.content
    assert client.get(f'/api/v1/map/{dataset}/tiles/{z}/{x}/{y}.mvt?records=invalid').status_code==422
