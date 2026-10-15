import hashlib
import json
import pytest
from app.source import read_snapshot


def test_snapshot_tampering_is_rejected(tmp_path):
    payload=b'{"features":[]}'
    (tmp_path/'page.geojson').write_bytes(payload+b' ')
    (tmp_path/'manifest.json').write_text(json.dumps({'count':0,'files':[{'path':'page.geojson','sha256':hashlib.sha256(payload).hexdigest()}]}))
    with pytest.raises(ValueError,match='checksum'):
        read_snapshot(tmp_path)


def test_download_batches_and_rejects_incomplete_pages(tmp_path, monkeypatch):
    from app import source
    ids=list(range(1000000,1000201))
    metadata={'fields':[{'name':n} for n in ('OBJECTID','TOWN_ID','LOC_ID','PROP_ID','OWNER1','USE_DESC')],
              'editingInfo':{'lastEditDate':1}}
    sizes=[]
    def request(client,endpoint,**params):
        if not endpoint:
            return metadata
        if params.get('returnIdsOnly'):
            return {'objectIds':ids}
        requested=list(map(int,params['objectIds'].split(',')))
        sizes.append(len(requested))
        return {'features':[{'properties':{'OBJECTID':i,'TOWN_ID':141},'geometry':None} for i in requested]}
    monkeypatch.setattr(source,'request',request)
    features,manifest=source.download(tmp_path/'complete')
    assert sizes==[100,100,1]
    assert len(features)==manifest['count']==201
    assert source.read_snapshot(tmp_path/'complete')[0]==features
    def incomplete(client,endpoint,**params):
        result=request(client,endpoint,**params)
        if 'features' in result:
            result['features'].pop()
        return result
    monkeypatch.setattr(source,'request',incomplete)
    with pytest.raises(ValueError,match='Incomplete'):
        source.download(tmp_path/'partial')
    assert not (tmp_path/'partial'/'manifest.json').exists()
