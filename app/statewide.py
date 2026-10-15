"""Import official current town packages at their original parcel/assessment grains."""
import concurrent.futures
import hashlib
import json
import zipfile
from collections import Counter,defaultdict
from pathlib import Path
from uuid import uuid4
import httpx
import pyogrio
import pyproj
import shapely
from psycopg.types.json import Jsonb
from app.db import connect
from app.normalize import clean, normalize

ROOT=Path('data/statewide')
PROCESSING='statewide-1'
pyogrio.set_gdal_config_options({'OGR_ARC_STEPSIZE':'1'})


def archive_path(town):
    file=ROOT/'archives'/f'{town:03d}.zip'
    checksum=json.loads(file.with_suffix('.json').read_text())['sha256']
    cache=Path('/tmp/prospect-intelligence-gdb')/checksum
    marker=cache/'complete'
    if not marker.exists():
        cache.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(file) as z:
            for member in z.infolist():
                target=(cache/member.filename).resolve()
                if not target.is_relative_to(cache.resolve()):raise ValueError('Unsafe archive member')
            z.extractall(cache)
        marker.write_text('verified extraction')
    return str(next(cache.rglob('*.gdb')))


def layer_rows(path,layer):
    meta,table=pyogrio.read_arrow(path,layer=layer,return_fids=True,read_geometry=False)
    rows=table.to_pylist()
    if meta.get('crs'):
        from pyogrio.raw import read
        gmeta,fids,geometries,_=read(path,layer=layer,columns=[],return_fids=True,force_2d=True)
        if len(rows)!=len(fids) or any(r[meta['fid_column']]!=int(fid) for r,fid in zip(rows,fids)):
            raise ValueError('Geometry and attribute ID mismatch')
        key=meta.get('geometry_name') or 'wkb_geometry'
        for row,geometry in zip(rows,geometries):row[key]=geometry
    return meta,rows


def describe(raw,descriptions):
    enriched=dict(raw)
    enriched['USE_DESC']=descriptions.get(clean(raw.get('USE_CODE')),raw.get('USE_DESC'))
    normalized=normalize(enriched)
    # Existing helper expects source geometry rows; assessor rows have different grain.
    normalized['issues']=[x for x in normalized['issues'] if x!='source_assessor_match_missing']
    return normalized


def geometry_values(meta,rows):
    key=meta.get('geometry_name') or 'wkb_geometry'
    if rows and key not in rows[0]:
        key=next((k for k,v in rows[0].items() if isinstance(v,bytes)),key)
    values=[r.pop(key,None) for r in rows]
    if not meta.get('crs'):
        return [None]*len(rows),['not_spatial']*len(rows)
    geometries=shapely.from_wkb(values)
    valid=shapely.is_valid(geometries) & ~shapely.is_empty(geometries)
    reasons=shapely.is_valid_reason(geometries)
    transformer=pyproj.Transformer.from_crs(meta['crs'],3857,always_xy=True)
    result=[None]*len(rows)
    if valid.any():
        transformed=shapely.transform(geometries[valid],transformer.transform,interleaved=False)
        encoded=shapely.to_wkb(shapely.set_srid(transformed,3857),hex=True,include_srid=True)
        for idx,value in zip(valid.nonzero()[0],encoded):result[idx]=value
    return result,[None if ok else str(reason) for ok,reason in zip(valid,reasons)]


def initialize():
    manifest=json.loads((ROOT/'manifest.json').read_text())
    if manifest['errors'] or len(manifest['municipalities'])!=351:
        raise ValueError('Download and verify all 351 archives first')
    fingerprint=hashlib.sha256((PROCESSING+json.dumps([(x['town_id'],x['sha256']) for x in manifest['municipalities']])).encode()).hexdigest()
    boundary_path=ROOT/'town-boundaries.geojson'
    if not boundary_path.exists():
        url='https://arcgisserver.digital.mass.gov/arcgisserver/rest/services/AGOL/L3_FTP_Download/MapServer/0/query'
        r=httpx.get(url,params={'f':'geojson','where':'1=1','outFields':'TOWN_ID,TOWN,FY','returnGeometry':'true','outSR':4326,'maxAllowableOffset':0.00015},timeout=120)
        r.raise_for_status();d=r.json()
        if len(d.get('features',[]))!=351:raise ValueError('Incomplete town boundaries')
        boundary_path.write_text(json.dumps(d))
    boundaries={f['properties']['TOWN_ID']:f['geometry'] for f in json.loads(boundary_path.read_text())['features']}
    with connect() as c:
        existing=c.execute('SELECT id FROM map_datasets WHERE fingerprint=%s',(fingerprint,)).fetchone()
        if existing:return existing['id'],manifest
        dataset=uuid4()
        c.execute('INSERT INTO map_datasets(id,fingerprint,manifest) VALUES (%s,%s,%s)',(dataset,fingerprint,Jsonb(manifest)))
        for item in manifest['municipalities']:
            c.execute('''INSERT INTO map_towns(dataset_id,town_id,name,fiscal_year,source,boundary)
                VALUES (%s,%s,%s,%s,%s,ST_SetSRID(ST_GeomFromGeoJSON(%s),4326))''',
                (dataset,item['town_id'],item['town'].title(),item['fiscal_year'],Jsonb(item),json.dumps(boundaries[item['town_id']])))
    return dataset,manifest


def import_town(dataset,item):
    town=item['town_id'];path=archive_path(town)
    # Recheck checksum just before parsing; publication must match preserved source manifest.
    h=hashlib.sha256()
    with (ROOT/'archives'/f'{town:03d}.zip').open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    if h.hexdigest()!=item['sha256']:raise ValueError('Archive checksum mismatch')
    layers=pyogrio.list_layers(path).tolist()
    tax=next((name for name,_ in layers if name.lower().endswith('taxpar')),None)
    assess=next((name for name,_ in layers if name.lower().endswith('assess')),None)
    if not tax:raise ValueError(f'Missing required parcel/assessment layers: {layers}')
    descriptions={}
    for name,_ in layers:
        if 'uc_lut' in name.lower():
            _,lookup=layer_rows(path,name)
            descriptions.update({clean(r.get('USE_CODE')):r.get('USE_DESC') for r in lookup})
    supplement=None
    if assess:
        ameta,assessments=layer_rows(path,assess)
    else:
        directory=ROOT/'assessment-supplements'/f'{town:03d}'
        if not (directory/'manifest.json').exists():
            from app.assessment_source import download
            download(town)
        supplement=json.loads((directory/'manifest.json').read_text())
        assessments=[]
        for file in supplement['files']:
            payload=(directory/file['file']).read_bytes()
            if hashlib.sha256(payload).hexdigest()!=file['sha256']:raise ValueError('Assessment supplement checksum mismatch')
            assessments.extend(f['attributes'] for f in json.loads(payload)['features'])
        if len(assessments)!=supplement['count']:raise ValueError('Incomplete Assessment supplement')
        if len({r['OBJECTID'] for r in assessments})!=len(assessments):raise ValueError('Duplicate Supplemental assessment IDs')
        ameta={'fid_column':'OBJECTID'}
        assess='MassGIS_Assess_Supplement'
    assessment_columns=[];matches=defaultdict(list)
    for raw in assessments:
        if raw.get('TOWN_ID') not in (None,town):raise ValueError('Wrong-town assessment')
        n=describe(raw,descriptions);loc=n['parcel_key']
        if loc:matches[loc].append(n['segment'])
        assessment_columns.append((dataset,town,raw[ameta['fid_column']],loc,n['assessment_key'],n['address'],
                                   n['owner_name'],n['owner_mail'],n['segment'],n['issues'],Jsonb(raw)))
    pmeta,parcels=layer_rows(path,tax)
    if not parcels:raise ValueError('Empty parcel layer')
    geoms,reasons=geometry_values(pmeta,parcels)
    parcel_columns=[];segments=Counter();quality=Counter()
    for raw,geom,reason in zip(parcels,geoms,reasons):
        if raw.get('TOWN_ID') not in (None,town):raise ValueError('Wrong-town parcel')
        loc=clean(raw.get('LOC_ID'));linked=matches.get(loc,[]);categories=set(linked)
        segment=next(iter(categories)) if len(categories)==1 else 'multiple_uses' if categories else 'unknown'
        issues=[]
        if reason:issues.append('invalid_geometry_quarantined')
        if not loc:issues.append('missing_parcel_identifier')
        if not linked:issues.append('no_assessment_match')
        segments[segment]+=1;quality.update(issues)
        parcel_columns.append((dataset,town,raw[pmeta['fid_column']],loc,clean(raw.get('MAP_PAR_ID')),segment,len(linked),issues,Jsonb(raw),geom))
    with connect() as c:
        c.execute('DELETE FROM map_assessments WHERE dataset_id=%s AND town_id=%s',(dataset,town))
        c.execute('DELETE FROM map_parcels WHERE dataset_id=%s AND town_id=%s',(dataset,town))
        c.execute('DELETE FROM map_supplementary WHERE dataset_id=%s AND town_id=%s',(dataset,town))
        with c.cursor().copy('COPY map_assessments(dataset_id,town_id,source_fid,loc_id,prop_id,address,owner_name,owner_mail,segment,issues,raw) FROM STDIN') as copy:
            for row in assessment_columns:copy.write_row(row)
        with c.cursor().copy('COPY map_parcels(dataset_id,town_id,source_fid,loc_id,map_par_id,segment,assessment_count,issues,raw,geom) FROM STDIN') as copy:
            for row in parcel_columns:copy.write_row(row)
        other=0;inventory={tax:len(parcels),assess:len(assessments)}
        for name,geometry_type in layers:
            if name in (tax,assess):continue
            meta,rows=layer_rows(path,name)
            geometry,_=geometry_values(meta,rows) if geometry_type else ([None]*len(rows),[])
            with c.cursor().copy('COPY map_supplementary(dataset_id,town_id,layer,source_fid,raw,geom) FROM STDIN') as copy:
                for raw,geom in zip(rows,geometry):copy.write_row((dataset,town,name,raw[meta['fid_column']],Jsonb(raw),geom))
            inventory[name]=len(rows);other+=len(rows)
        stats={'segments':dict(segments),'issues':dict(quality),'layers':inventory,'use_descriptions':descriptions}
        if supplement:
            c.execute('UPDATE map_towns SET source=source || %s WHERE dataset_id=%s AND town_id=%s',
                      (Jsonb({'assessment_supplement':supplement}),dataset,town))
        c.execute("UPDATE map_towns SET state='ready',error=NULL,parcel_count=%s,assessment_count=%s,other_count=%s,quarantine_count=%s,stats=%s WHERE dataset_id=%s AND town_id=%s",
                  (len(parcels),len(assessments),other,quality['invalid_geometry_quarantined'],Jsonb(stats),dataset,town))
    return len(parcels),len(assessments)


def main():
    with connect() as guard:
        guard.autocommit=True
        if not guard.execute('SELECT pg_try_advisory_lock(351001) AS ok').fetchone()['ok']:raise RuntimeError('Statewide import already running')
        dataset,manifest=initialize();failed=[]
        with connect() as c:
            c.execute("UPDATE map_datasets SET state='loading' WHERE id=%s AND state<>'ready'",(dataset,))
        with connect() as c:
            ready={r['town_id'] for r in c.execute("SELECT town_id FROM map_towns WHERE dataset_id=%s AND state='ready'",(dataset,)).fetchall()}
        pending=[item for item in manifest['municipalities'] if item['town_id'] not in ready]
        completed=len(ready)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures={pool.submit(import_town,dataset,item):item for item in pending}
            for future in concurrent.futures.as_completed(futures):
                item=futures[future]
                try:
                    parcels,assessments=future.result();completed+=1
                    print(f'{completed}/351 {item["town"]}: {parcels} parcels, {assessments} assessments',flush=True)
                except Exception as exc:
                    failed.append(item['town'])
                    with connect() as c:
                        c.execute("UPDATE map_towns SET state='failed',error=%s WHERE dataset_id=%s AND town_id=%s",(str(exc)[:1000],dataset,item['town_id']))
                    print(f'FAILED {item["town"]}: {exc}',flush=True)
        with connect() as c:
            remaining=c.execute("SELECT count(*) AS n FROM map_towns WHERE dataset_id=%s AND state!='ready'",(dataset,)).fetchone()['n']
            if not remaining:
                c.execute("UPDATE map_datasets SET state='ready',completed_at=now() WHERE id=%s",(dataset,))
            else:
                c.execute("UPDATE map_datasets SET state='failed',completed_at=now() WHERE id=%s",(dataset,))
            c.execute('ANALYZE map_parcels');c.execute('ANALYZE map_assessments')
        print(json.dumps({'dataset':str(dataset),'remaining':remaining,'failed':failed}),flush=True)
        if remaining:raise SystemExit(1)

if __name__=='__main__':main()
