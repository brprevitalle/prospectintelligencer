"""Real PostGIS tests in an isolated schema, never truncate the local town dataset."""
import copy
import os
from uuid import uuid4
import pytest
from psycopg import sql
from fastapi.testclient import TestClient
from app import db
from app.pipeline import publish
from app.source import SOURCE

pytestmark = pytest.mark.skipif(not os.environ.get('DATABASE_URL'),reason='PostGIS DATABASE_URL required')


@pytest.fixture
def conn():
    schema='test_'+uuid4().hex
    with db.connect() as c:
        c.execute('CREATE EXTENSION IF NOT EXISTS postgis')
        c.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        c.execute(sql.SQL('SET search_path TO {},public').format(sql.Identifier(schema)))
        from pathlib import Path
        for migration in sorted(Path('migrations').glob('*.sql')):
            c.execute(migration.read_text())
        c.commit()
        try:
            yield c
        finally:
            c.rollback()
            c.execute('SET search_path TO public')
            c.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


def source():
    return [{'type':'Feature','properties':{'OBJECTID':1,'TOWN_ID':141,'LOC_ID':'PARCEL-A','PROP_ID':'ASSESSMENT-A',
             'OWNER1':' TEST  LLC ','SITE_ADDR':'1 MAIN ST','UNITS':0,'USE_DESC':'Single Family Residential'},
             'geometry':{'type':'Polygon','coordinates':[[[-71.57,42.39],[-71.56,42.39],[-71.56,42.40],[-71.57,42.39]]]}}]


def manifest(count=1):
    return {'town_id':141,'count':count,'source':SOURCE,'source_edited_at':1}


def start(c):
    run=uuid4()
    c.execute("INSERT INTO runs(id,town_id,state,stage) VALUES (%s,141,'running','test')",(run,))
    c.commit()
    return run


def test_replay_and_refresh_preserve_notes(conn):
    run=start(conn)
    with conn.transaction():
        first,reused=publish(conn,run,source(),manifest())
    assert not reused
    conn.execute("INSERT INTO property_notes VALUES (141,'PARCEL-A','Reviewed owner',now())")
    conn.commit()
    with conn.transaction():
        same,reused=publish(conn,run,source(),manifest())
    assert same==first and reused
    changed=source()
    changed[0]['properties']['OWNER1']='NEW OWNER'
    with conn.transaction():
        second,_=publish(conn,run,changed,manifest())
    assert second != first
    with conn.transaction():
        publish(conn,run,source(),manifest())
    assert conn.execute('SELECT active_publication FROM towns').fetchone()['active_publication']==second
    assert conn.execute('SELECT note FROM property_notes').fetchone()['note']=='Reviewed owner'
    assert conn.execute('SELECT count(*) AS n FROM publications').fetchone()['n']==2


@pytest.mark.parametrize('kind',['duplicate','wrong_town','invalid_geometry','missing_geometry','count'])
def test_failed_import_keeps_previous_publication(conn,kind):
    run=start(conn)
    with conn.transaction():
        previous,_=publish(conn,run,source(),manifest())
    bad=source()
    info=manifest()
    if kind=='duplicate':
        bad.append(copy.deepcopy(bad[0]));info['count']=2
    elif kind=='wrong_town':
        bad[0]['properties']['TOWN_ID']=142
    elif kind=='invalid_geometry':
        bad[0]['geometry']['coordinates']=[[[-181,42],[-180,43],[-181,43],[-181,42]]]
    elif kind=='missing_geometry':
        bad[0]['geometry']=None
    else:
        info['count']=2
    with pytest.raises(ValueError):
        with conn.transaction():
            publish(conn,run,bad,info)
    assert conn.execute('SELECT active_publication FROM towns').fetchone()['active_publication']==previous
    assert conn.execute('SELECT count(*) AS n FROM publications').fetchone()['n']==1


def test_repeated_assessments_flagged_not_merged(conn):
    features=source()
    other=copy.deepcopy(features[0]);other['properties']['OBJECTID']=2
    features.append(other)
    run=start(conn)
    with conn.transaction():
        pub,_=publish(conn,run,features,manifest(2))
    rows=conn.execute('SELECT issues FROM source_records').fetchall()
    assert len(rows)==2
    assert all('repeated_assessment_identifier' in r['issues'] for r in rows)


def test_api_filters_and_publication_contract(conn,monkeypatch):
    from contextlib import contextmanager
    from app import api
    run=start(conn)
    with conn.transaction():
        pub,_=publish(conn,run,source(),manifest())
    @contextmanager
    def connection():
        yield conn
    monkeypatch.setattr(api,'connect',connection)
    client=TestClient(api.app)
    data=client.get('/api/v1/properties',params={'q':'test','publication':str(pub)}).json()
    assert data['counts']['source_records']==1
    assert client.get('/api/v1/properties',params={'q':"' OR 1=1 --"}).json()['counts']['source_records']==0
    assert client.get('/api/v1/properties',params={'q':'%'}).json()['counts']['source_records']==0
    assert client.get('/api/v1/properties?limit=9999').status_code==422
    assert client.get('/api/v1/properties?publication='+str(uuid4())).status_code==404
    assert client.get('/api/v1/properties/1?publication='+str(pub)).json()['record']['raw']['OWNER1']==' TEST  LLC '


def test_topology_error_is_preserved_and_quarantined(conn):
    features=source()
    geometry={'type':'Polygon','coordinates':[[[-71,42],[-70,43],[-71,43],[-70,42],[-71,42]]]}
    features[0]['geometry']=geometry
    run=start(conn)
    with conn.transaction():
        publish(conn,run,features,manifest())
    row=conn.execute('SELECT geom,raw_geometry,issues FROM source_records').fetchone()
    assert row['geom'] is None
    assert row['raw_geometry']==geometry
    assert 'invalid_geometry_quarantined' in row['issues']
