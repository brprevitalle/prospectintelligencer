"""Acquire a missing assessor table from the separate official MassGIS service."""
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
import httpx

SOURCE='https://arcgisserver.digital.mass.gov/arcgisserver/rest/services/AGOL/MassachusettsPropertyTaxParcels/FeatureServer/4'



def download(town):
    ROOT=Path('data/statewide/assessment-supplements')/f'{town:03d}'
    ROOT.mkdir(parents=True,exist_ok=True)
    with httpx.Client(timeout=120) as c:
        def query(**params):
            for attempt in range(4):
                try:
                    r=c.get(SOURCE+'/query',params={'f':'json',**params});r.raise_for_status();d=r.json()
                    if 'error' in d:raise ValueError(d['error'])
                    return d
                except (httpx.HTTPError,ValueError):
                    if attempt==3:raise
                    time.sleep(2**attempt)
        ids=sorted(query(where=f'TOWN_ID={town}',returnIdsOnly='true')['objectIds'])
        files=[]
        for start in range(0,len(ids),2000):
            expected=ids[start:start+2000]
            path=ROOT/f'page-{start:06d}.json'
            if path.exists():
                data=json.loads(path.read_text())
            else:
                data=query(where=f'TOWN_ID={town} AND OBJECTID >= {expected[0]} AND OBJECTID <= {expected[-1]}',
                           outFields='*',orderByFields='OBJECTID',resultRecordCount=2000,returnGeometry='false')
                path.write_text(json.dumps(data,separators=(',',':')))
            actual=[f['attributes']['OBJECTID'] for f in data['features']]
            if actual!=expected or any(f['attributes']['TOWN_ID']!=town for f in data['features']):
                raise ValueError('Incomplete or incorrect assessor batch')
            files.append({'file':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'count':len(actual)})
            print(f'{min(start+2000,len(ids))}/{len(ids)}',flush=True)
        if ids!=sorted(query(where=f'TOWN_ID={town}',returnIdsOnly='true')['objectIds']):
            raise ValueError('Source IDs changed during download')
        manifest={'source':SOURCE,'town_id':town,'count':len(ids),'retrieved_at':datetime.now(timezone.utc).isoformat(),'files':files}
        (ROOT/'manifest.json').write_text(json.dumps(manifest,indent=2))
        print(f'Town {town} assessment supplement complete.',flush=True)
        return manifest

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('town',type=int);download(p.parse_args().town)
