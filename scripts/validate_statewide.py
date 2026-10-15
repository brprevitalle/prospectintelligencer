"""Read-only final checks against the completed statewide publication and source manifests."""
import hashlib
import json
from pathlib import Path
from app.db import connect

root=Path('data/statewide')
manifest=json.loads((root/'manifest.json').read_text())
assert not manifest['errors']
assert {x['town_id'] for x in manifest['municipalities']}==set(range(1,352))
for item in manifest['municipalities']:
    h=hashlib.sha256()
    with (root/'archives'/f"{item['town_id']:03d}.zip").open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    assert h.hexdigest()==item['sha256'],item['town']

with connect() as c:
    dataset=c.execute("SELECT id,state FROM map_datasets ORDER BY created_at DESC LIMIT 1").fetchone()
    assert dataset and dataset['state']=='ready','Statewide import is not complete'
    ident=dataset['id']
    towns=c.execute('SELECT * FROM map_towns WHERE dataset_id=%s',(ident,)).fetchall()
    assert len(towns)==351 and all(t['state']=='ready' for t in towns)
    counts={}
    for table in ('map_parcels','map_assessments','map_supplementary'):
        counts[table]={r['town_id']:r['n'] for r in c.execute(f'SELECT town_id,count(*) AS n FROM {table} WHERE dataset_id=%s GROUP BY town_id',(ident,)).fetchall()}
    for town in towns:
        tid=town['town_id']
        assert counts['map_parcels'].get(tid,0)==town['parcel_count'],town['name']
        assert counts['map_assessments'].get(tid,0)==town['assessment_count'],town['name']
        assert counts['map_supplementary'].get(tid,0)==town['other_count'],town['name']
    q=c.execute('SELECT count(*) AS n FROM map_parcels WHERE dataset_id=%s AND geom IS NULL',(ident,)).fetchone()['n']
    assert q==sum(t['quarantine_count'] for t in towns)
    supplements=[]
    for town in towns:
        supplement=town['source'].get('assessment_supplement')
        if not supplement:continue
        seen=set();rows=0
        for file in supplement['files']:
            payload=(root/'assessment-supplements'/f"{town['town_id']:03d}"/file['file']).read_bytes()
            assert hashlib.sha256(payload).hexdigest()==file['sha256']
            features=json.loads(payload)['features']
            assert len(features)==file['count']
            for feature in features:
                raw=feature['attributes']
                assert raw['TOWN_ID']==town['town_id'] and raw['OBJECTID'] not in seen
                seen.add(raw['OBJECTID'])
            rows+=len(features)
        assert rows==supplement['count']==town['assessment_count']
        supplements.append({'town':town['name'],'rows':rows})
    result={'dataset':str(ident),'towns':351,'archive_bytes':sum(x['bytes'] for x in manifest['municipalities']),
            'parcels':sum(counts['map_parcels'].values()),'assessments':sum(counts['map_assessments'].values()),
            'supplementary_records':sum(counts['map_supplementary'].values()),'quarantined_parcels':q,
            'assessment_supplements':supplements,'all_archive_checksums_match':True,'all_town_counts_match':True}
    print(json.dumps(result,indent=2))
