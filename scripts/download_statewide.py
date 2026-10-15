"""Download all current official municipality File Geodatabases; resumable and checksummed."""
import concurrent.futures
import hashlib
import json
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
import httpx

ROOT=Path('data/statewide')
CATALOG='https://arcgisserver.digital.mass.gov/arcgisserver/rest/services/AGOL/L3_FTP_Download/MapServer/0/query'


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def fetch(item):
    a=item['attributes']; town=a['TOWN_ID']
    path=ROOT/'archives'/f'{town:03d}.zip'; record=path.with_suffix('.json')
    if path.exists() and record.exists():
        existing=json.loads(record.read_text())
        if existing['url']==a['FGDB_LINK'] and existing['sha256']==digest(path):
            return existing
    if not a['FGDB_LINK'].startswith('https://s3.us-east-1.amazonaws.com/download.massgis.digital.mass.gov/gdbs/l3parcels/'):
        raise ValueError('Unexpected archive origin')
    for attempt in range(4):
        try:
            with httpx.Client(timeout=180,follow_redirects=True) as client:
                with client.stream('GET',a['FGDB_LINK']) as response:
                    response.raise_for_status()
                    partial=path.with_suffix('.part')
                    with partial.open('wb') as f:
                        for chunk in response.iter_bytes(1024*1024):f.write(chunk)
                    size=response.headers.get('content-length')
                    if size and partial.stat().st_size!=int(size):raise ValueError('Incomplete archive')
                    with zipfile.ZipFile(partial) as z:
                        bad=z.testzip()
                        if bad:raise ValueError('ZIP checksum failure')
                    partial.replace(path)
                    result={'town_id':town,'town':a['TOWN'],'fiscal_year':a['FY'],'url':a['FGDB_LINK'],
                            'bytes':path.stat().st_size,'sha256':digest(path),'etag':response.headers.get('etag'),
                            'last_modified':response.headers.get('last-modified'),
                            'retrieved_at':datetime.now(timezone.utc).isoformat(),'note':a.get('NOTE')}
                    record.write_text(json.dumps(result,indent=2))
                    return result
        except (httpx.HTTPError,ValueError,zipfile.BadZipFile):
            if attempt==3:raise
            time.sleep(2**attempt)


def main():
    (ROOT/'archives').mkdir(parents=True,exist_ok=True)
    catalog_path=ROOT/'download-catalog.json'
    if not catalog_path.exists():
        r=httpx.get(CATALOG,params={'f':'json','where':'1=1','outFields':'*','returnGeometry':'false'},timeout=90)
        r.raise_for_status();catalog_path.write_bytes(r.content)
    catalog=json.loads(catalog_path.read_text())
    features=catalog['features']
    if len(features)!=351 or len({f['attributes']['TOWN_ID'] for f in features})!=351:
        raise ValueError('Expected exactly 351 unique municipalities')
    results=[];errors=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures={pool.submit(fetch,f):f['attributes']['TOWN'] for f in features}
        for future in concurrent.futures.as_completed(futures):
            try:
                r=future.result();results.append(r)
                print(f"{len(results)}/351 {r['town']} {r['bytes']/1024/1024:.1f} MB",flush=True)
            except Exception as exc:
                errors.append({'town':futures[future],'error':str(exc)})
                print(f'FAILED {futures[future]}: {exc}',flush=True)
            status={'complete':len(results),'expected':351,'bytes':sum(r['bytes'] for r in results),'errors':errors}
            (ROOT/'download-status.json').write_text(json.dumps(status,indent=2))
    manifest={'catalog_url':CATALOG,'completed_at':datetime.now(timezone.utc).isoformat(),
              'municipalities':sorted(results,key=lambda r:r['town_id']),'errors':errors}
    (ROOT/'manifest.json').write_text(json.dumps(manifest,indent=2))
    if errors:raise SystemExit(1)
    print('All 351 archives verified.',flush=True)

if __name__=='__main__':main()
