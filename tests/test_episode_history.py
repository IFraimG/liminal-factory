import pytest
from backend.storage.db import Store
from backend.orchestration.engine import Engine
from backend.models.schema import Settings

def test_full_history_is_authenticated_scoped_and_not_limited(tmp_path,monkeypatch):
    monkeypatch.setenv('LIMINAL_DATA',str(tmp_path/'api'));monkeypatch.setenv('LIMINAL_TOKEN','test-token')
    import backend.main as main
    from fastapi.testclient import TestClient
    store=Store(tmp_path/'db');engine=Engine(store,tmp_path/'episodes',Settings())
    first=engine.create({'name':'first'});second=engine.create({'name':'second'})
    for i in range(350):store.log(first,'metadata',f'event {i}')
    store.log(second,'metadata','other episode')
    monkeypatch.setattr(main,'engine',engine);monkeypatch.setattr(main,'store',store)
    with TestClient(main.app) as client:
        assert client.get(f'/episodes/{first}/history').status_code==401
        client.headers['Authorization']='Bearer '+main.TOKEN
        result=client.get(f'/episodes/{first}/history');assert result.status_code==200
        events=result.json()['logs'];assert len(events)==351
        assert all(row['episode']==first for row in events)
        assert any(row['message']=='event 0' for row in events)
