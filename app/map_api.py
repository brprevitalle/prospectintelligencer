"""Version-pinned statewide map API. All property queries read the local database."""
import json
from functools import lru_cache
from uuid import UUID
from typing import Literal
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from app.db import connect

router=APIRouter(prefix='/api/v1/map')


def dataset_exists(c,dataset):
    row=c.execute('SELECT id,state FROM map_datasets WHERE id=%s',(dataset,)).fetchone()
    if not row:raise HTTPException(404,'Dataset not found')
    return row


@router.get('/catalog')
def catalog():
    with connect() as c:
        d=c.execute("SELECT id,state,created_at,completed_at FROM map_datasets ORDER BY (state='ready') DESC,created_at DESC LIMIT 1").fetchone()
        if not d:raise HTTPException(404,'Statewide import has not started')
        towns=c.execute('''SELECT town_id,name,fiscal_year,state,parcel_count,assessment_count,other_count,
            quarantine_count,stats,ST_XMin(Box3D(boundary)) AS west,ST_YMin(Box3D(boundary)) AS south,
            ST_XMax(Box3D(boundary)) AS east,ST_YMax(Box3D(boundary)) AS north
            FROM map_towns WHERE dataset_id=%s ORDER BY name''',(d['id'],)).fetchall()
        for town in towns:town['stats']={k:v for k,v in town['stats'].items() if k!='use_descriptions'}
        return {'dataset':d,'towns':towns,'totals':{
            'towns_ready':sum(t['state']=='ready' for t in towns),'towns_expected':len(towns),
            'parcels':sum(t['parcel_count'] for t in towns),'assessments':sum(t['assessment_count'] for t in towns),
            'supporting':sum(t['other_count'] for t in towns),
            'quarantined':sum(t['quarantine_count'] for t in towns)},
            'source':'MassGIS current municipal File Geodatabase packages',
            'geometry_note':'Curves linearized for display at a 1-degree angular step; original archives preserved.'}


@router.get('/{dataset}/towns.geojson')
def boundaries(dataset:UUID):
    with connect() as c:
        dataset_exists(c,dataset)
        rows=c.execute('''SELECT town_id,name,fiscal_year,state,parcel_count,
            ST_AsGeoJSON(boundary)::json AS geometry FROM map_towns WHERE dataset_id=%s''',(dataset,)).fetchall()
    return {'type':'FeatureCollection','features':[{'type':'Feature','id':r['town_id'],'geometry':r.pop('geometry'),'properties':r} for r in rows]}


@lru_cache(maxsize=128)
def tile_data(dataset,z,x,y,segment,town,records="parcels"):
    with connect() as c:
        c.execute("SET LOCAL statement_timeout='8s'")
        dataset_exists(c,dataset)
        clauses=['dataset_id=%s','geom && ST_TileEnvelope(%s,%s,%s, margin => 0.015625)']
        args=[dataset,z,x,y]
        if segment and records=='parcels':clauses.append('segment=%s');args.append(segment)
        if town:clauses.append('town_id=%s');args.append(town)
        where=' AND '.join(clauses)
        table='map_supplementary' if records=='supporting' else 'map_parcels'
        columns="source_fid AS id,source_fid,town_id,layer,'supporting'::text AS segment,geom" if records=='supporting' else 'id,town_id,segment,assessment_count,geom'
        attributes='id,source_fid,town_id,layer,segment' if records=='supporting' else 'id,town_id,segment,assessment_count'
        row=c.execute(f'''WITH candidates AS MATERIALIZED (
            SELECT {columns} FROM {table} WHERE {where} LIMIT 20001
            ), tile AS (
            SELECT {attributes},
            ST_AsMVTGeom(geom,ST_TileEnvelope(%s,%s,%s),4096,64,true) AS geom FROM candidates
            ) SELECT (SELECT count(*) FROM candidates) AS n,ST_AsMVT(tile,'parcels',4096,'geom','id') AS tile FROM tile''',[*args,z,x,y]).fetchone()
        if row['n']>20000:raise HTTPException(413,'Zoom in to display parcels in this area')
        data=bytes(row['tile'] or b'')
        if len(data)>3_000_000:raise HTTPException(413,'Zoom in; tile exceeds display size limit')
        return data


@router.get('/{dataset}/tiles/{z}/{x}/{y}.mvt')
def tile(dataset:UUID,z:int,x:int,y:int,segment:str=Query('',max_length=80),town:int=Query(0,ge=0,le=351),records:Literal['parcels','supporting']='parcels'):
    if not 0<=z<=20 or not 0<=x<2**z or not 0<=y<2**z:raise HTTPException(422,'Invalid tile coordinates')
    if z<13:return Response(b'',media_type='application/vnd.mapbox-vector-tile')
    with connect() as c:state=dataset_exists(c,dataset)['state']
    # Loading snapshots bypass the cache so newly committed towns become visible immediately.
    data=(tile_data if state=='ready' else tile_data.__wrapped__)(dataset,z,x,y,segment,town,records)
    return Response(data,media_type='application/vnd.mapbox-vector-tile',headers={'Cache-Control':'private, max-age=3600' if state=='ready' else 'no-store'})


@router.get('/{dataset}/search')
def search(dataset:UUID,q:str=Query('',max_length=150),town:int=Query(0,ge=0,le=351),
           segment:str=Query('',max_length=80),limit:int=Query(30,ge=1,le=100),offset:int=Query(0,ge=0,le=10000)):
    if q and len(q.strip())<3:raise HTTPException(422,'Enter at least three characters')
    with connect() as c:
        c.execute("SET LOCAL statement_timeout='8s'");dataset_exists(c,dataset)
        clauses=['a.dataset_id=%s'];args=[dataset]
        if town:clauses.append('a.town_id=%s');args.append(town)
        if segment:
            clauses.append('EXISTS (SELECT 1 FROM map_parcels pf WHERE pf.dataset_id=a.dataset_id AND pf.town_id=a.town_id AND pf.loc_id=a.loc_id AND pf.segment=%s)')
            args.append(segment)
        if q:
            term='%'+q.strip().upper().replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
            clauses.append('(a.address LIKE %s OR a.owner_name LIKE %s)');args.extend([term,term])
        where=' AND '.join(clauses)
        rows=c.execute(f'''SELECT a.id AS assessment_id,a.town_id,t.name AS town,a.address,a.owner_name,a.owner_mail,
            a.prop_id,a.loc_id,a.segment,a.issues,a.raw->>'FY' AS fiscal_year,
            p.id AS parcel_id,ST_X(ST_Transform(ST_PointOnSurface(p.geom),4326)) AS lng,
            ST_Y(ST_Transform(ST_PointOnSurface(p.geom),4326)) AS lat
            FROM (SELECT * FROM map_assessments a WHERE {where} ORDER BY a.id LIMIT %s OFFSET %s) a
            JOIN map_towns t ON t.dataset_id=a.dataset_id AND t.town_id=a.town_id
            LEFT JOIN LATERAL (SELECT id,geom FROM map_parcels p WHERE p.dataset_id=a.dataset_id AND p.town_id=a.town_id
                AND p.loc_id=a.loc_id ORDER BY (geom IS NULL),id LIMIT 1) p ON true
            ORDER BY a.id''',[*args,limit+1,offset]).fetchall()
        return {'dataset':str(dataset),'records':rows[:limit],'has_more':len(rows)>limit,'offset':offset,
                'grain':'assessment records; one parcel may have several assessments'}


@router.get('/{dataset}/parcels/{parcel_id}')
def parcel(dataset:UUID,parcel_id:int,offset:int=Query(0,ge=0,le=100000)):
    with connect() as c:
        dataset_exists(c,dataset)
        p=c.execute('''SELECT p.id,p.town_id,t.name AS town,t.fiscal_year,t.source,p.loc_id,p.map_par_id,p.segment,p.assessment_count,
            p.issues,p.raw,ST_AsGeoJSON(ST_Transform(p.geom,4326))::json AS geometry
            FROM map_parcels p JOIN map_towns t ON t.dataset_id=p.dataset_id AND t.town_id=p.town_id
            WHERE p.dataset_id=%s AND p.id=%s''',(dataset,parcel_id)).fetchone()
        if not p:raise HTTPException(404,'Parcel not found')
        rows=c.execute('''SELECT id,prop_id,address,owner_name,owner_mail,segment,issues,raw FROM map_assessments
            WHERE dataset_id=%s AND town_id=%s AND loc_id=%s ORDER BY id LIMIT 100 OFFSET %s''',
            (dataset,p['town_id'],p['loc_id'],offset)).fetchall()
        descriptions=c.execute('SELECT stats->\'use_descriptions\' AS descriptions FROM map_towns WHERE dataset_id=%s AND town_id=%s',(dataset,p['town_id'])).fetchone()['descriptions'] or {}
        for r in rows:r['use_description']=descriptions.get((r['raw'].get('USE_CODE') or '').strip().upper())
        return {'dataset':str(dataset),'parcel':p,'assessments':rows,'assessment_offset':offset,
                'assessment_has_more':offset+len(rows)<p['assessment_count'],
                'contacts':'Not enriched. Reported ownership does not establish purchasing responsibility.'}


@router.get('/{dataset}/parcels/{parcel_id}/abutters')
def abutters(dataset:UUID,parcel_id:int):
    with connect() as c:
        c.execute("SET LOCAL statement_timeout='8s'")
        p=c.execute('SELECT geom FROM map_parcels WHERE dataset_id=%s AND id=%s',(dataset,parcel_id)).fetchone()
        if not p:raise HTTPException(404,'Parcel not found')
        if p['geom'] is None:raise HTTPException(409,'Geometry is quarantined')
        rows=c.execute('''SELECT b.id,b.town_id,b.loc_id,b.map_par_id,b.segment
            FROM map_parcels a JOIN map_parcels b ON a.dataset_id=b.dataset_id AND a.id<>b.id
            AND b.geom && ST_Expand(a.geom,1)
            WHERE a.dataset_id=%s AND a.id=%s
            AND ST_DWithin(ST_Transform(a.geom,26986),ST_Transform(b.geom,26986),0.1)
            ORDER BY b.id LIMIT 101''',(dataset,parcel_id)).fetchall()
        return {'records':rows[:100],'has_more':len(rows)>100,
                'method':'Candidate neighbors intersecting or within 0.1 meters in EPSG:26986; not a legal abutters list.'}


@router.get('/{dataset}/supporting')
def supporting_records(dataset:UUID,q:str=Query('',max_length=150),town:int=Query(0,ge=0,le=351),
                       limit:int=Query(30,ge=1,le=100),offset:int=Query(0,ge=0,le=10000)):
    if q and len(q.strip())<3:raise HTTPException(422,'Enter at least three characters')
    with connect() as c:
        dataset_exists(c,dataset);c.execute("SET LOCAL statement_timeout='8s'")
        clauses=['s.dataset_id=%s'];args=[dataset]
        if town:clauses.append('s.town_id=%s');args.append(town)
        if q:
            term='%'+q.strip().replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
            clauses.append('(s.raw::text ILIKE %s OR s.layer ILIKE %s)');args.extend([term,term])
        where=' AND '.join(clauses)
        rows=c.execute(f'''SELECT s.town_id,t.name AS town,s.layer,s.source_fid,s.raw,
            ST_X(ST_Transform(ST_PointOnSurface(s.geom),4326)) AS lng,
            ST_Y(ST_Transform(ST_PointOnSurface(s.geom),4326)) AS lat
            FROM (SELECT * FROM map_supplementary s WHERE {where}
                ORDER BY town_id,(geom IS NULL),layer,source_fid LIMIT %s OFFSET %s) s
            JOIN map_towns t ON t.dataset_id=s.dataset_id AND t.town_id=s.town_id
            ORDER BY s.town_id,(s.geom IS NULL),s.layer,s.source_fid''',[*args,limit+1,offset]).fetchall()
        return {'dataset':str(dataset),'records':rows[:limit],'has_more':len(rows)>limit,'offset':offset}


@router.get('/{dataset}/supporting/{town_id}/{layer}/{source_fid}')
def supporting_detail(dataset:UUID,town_id:int,layer:str,source_fid:int):
    with connect() as c:
        dataset_exists(c,dataset)
        row=c.execute('''SELECT s.town_id,t.name AS town,s.layer,s.source_fid,s.raw,t.source,
            ST_AsGeoJSON(ST_Transform(s.geom,4326))::json AS geometry
            FROM map_supplementary s JOIN map_towns t ON t.dataset_id=s.dataset_id AND t.town_id=s.town_id
            WHERE s.dataset_id=%s AND s.town_id=%s AND s.layer=%s AND s.source_fid=%s''',
            (dataset,town_id,layer,source_fid)).fetchone()
        if not row:raise HTTPException(404,'Supporting record not found')
        return {'dataset':str(dataset),'record':row}
