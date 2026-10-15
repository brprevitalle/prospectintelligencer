"""Read-only MassGIS adapter. Fixed town allowlist; no arbitrary remote URLs."""
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
import httpx

SOURCE = 'https://services1.arcgis.com/hGdibHYSPO59RG1h/ArcGIS/rest/services/Massachusetts_Property_Tax_Parcels/FeatureServer/0'


def request(client, endpoint, **params):
    for attempt in range(4):
        try:
            response = client.get(SOURCE + endpoint, params={'f': 'json', **params})
            response.raise_for_status()
            result = response.json()
            if 'error' in result:
                raise RuntimeError(f"Source error: {result['error']}")
            return result
        except (httpx.HTTPError, ValueError):
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)


def download(directory, town_id=141):
    if town_id != 141:
        raise ValueError('Only Hudson (141) is enabled in this first adapter')
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    with httpx.Client(timeout=90) as client:
        metadata = request(client, '')
        fields = {f['name'] for f in metadata['fields']}
        required = {'OBJECTID', 'TOWN_ID', 'LOC_ID', 'PROP_ID', 'OWNER1', 'USE_DESC'}
        if not required <= fields:
            raise ValueError(f'Source schema changed; missing {required - fields}')
        edited = metadata['editingInfo']['lastEditDate']
        ids = sorted(request(client, '/query', where=f'TOWN_ID = {town_id}', returnIdsOnly='true')['objectIds'])
        if not ids or len(ids) != len(set(ids)):
            raise ValueError('Source returned empty or duplicate object IDs')
        all_features = []
        files = []
        for start in range(0, len(ids), 100):
            batch = ids[start:start + 100]
            page = request(client, '/query', f='geojson', objectIds=','.join(map(str, batch)),
                           outFields='*', returnGeometry='true', outSR=4326)
            features = page.get('features', [])
            actual = [f['properties']['OBJECTID'] for f in features]
            if len(actual) != len(batch) or set(actual) != set(batch):
                raise ValueError('Incomplete or duplicate source page; publication blocked')
            if any(f['properties'].get('TOWN_ID') != town_id for f in features):
                raise ValueError('Wrong-town record; publication blocked')
            payload = json.dumps(page, sort_keys=True, separators=(',', ':')).encode()
            filename = f'page-{start:06d}.geojson'
            (directory / filename).write_bytes(payload)
            files.append({'path': filename, 'sha256': hashlib.sha256(payload).hexdigest()})
            all_features.extend(features)
        after = request(client, '')['editingInfo']['lastEditDate']
        if after != edited:
            raise ValueError('Source changed during acquisition; retry for a consistent snapshot')
        manifest = dict(source=SOURCE, town_id=town_id, source_edited_at=edited,
                        retrieved_at=datetime.now(timezone.utc).isoformat(),
                        count=len(ids), files=files, metadata=metadata)
        (directory / 'manifest.json').write_text(json.dumps(manifest, indent=2))
        return all_features, manifest


def read_snapshot(directory):
    directory = Path(directory)
    manifest = json.loads((directory / 'manifest.json').read_text())
    features = []
    for file in manifest['files']:
        if Path(file['path']).name != file['path']:
            raise ValueError('Invalid snapshot filename')
        payload = (directory / file['path']).read_bytes()
        if hashlib.sha256(payload).hexdigest() != file['sha256']:
            raise ValueError('Snapshot checksum mismatch')
        features.extend(json.loads(payload)['features'])
    if len(features) != manifest['count']:
        raise ValueError('Snapshot record count mismatch')
    return features, manifest
