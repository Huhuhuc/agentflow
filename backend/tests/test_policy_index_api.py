import pytest
from test_agent import store, client
from app.config import settings
from app.models import ServicePolicy, PolicyIndex
from app.policy_index import enqueue
from app.index_worker import batch, LocalEmbedder


@pytest.fixture(autouse=True)
def isolate_business_watchdog(monkeypatch):
    # These are index API tests, not business recovery tests. StaticPool shares a
    # single SQLite connection; unrelated background commits would race setup.
    async def idle(factory, stop):
        await stop.wait()
    monkeypatch.setattr('app.business_recovery.watchdog', idle)


def policy(db, user):
    p=ServicePolicy(tenant_id=user.tenant_id,slug='refund',version=1,title='Refund',
        text='Refund within seven days.',topic='refund',order_status='delivered')
    db.add(p);db.commit()
    return p


def test_api_enqueue_idempotency_and_status(client,store,monkeypatch):
    db,factory,user,_=store
    p=policy(db,user);c,h=client
    path=f'/api/v1/service/policies/{p.id}/indexes'
    monkeypatch.setattr(settings,'embedding_model_path','')
    assert c.post(path,headers=h).status_code==503
    monkeypatch.setattr(settings,'embedding_model_path','local-model')
    monkeypatch.setattr(settings,'embedding_revision','fixture-v1')
    first=c.post(path,headers=h)
    assert first.status_code==202
    assert c.post(path,headers=h).json()['id']==first.json()['id']
    assert c.get(path,headers=h).json()[0]['status']=='pending'
    results=batch(factory,lambda texts,revision:[[1,2] for _ in texts])
    assert results[0]['ready']
    assert c.get(path,headers=h).json()[0]['status']=='ready'
    assert c.post('/api/v1/service/indexes/'+first.json()['id']+'/retry',headers=h).status_code==409


def test_cross_tenant_and_viewer(client,store,monkeypatch):
    from app.models import Tenant
    db,_,user,_=store;c,h=client
    other=Tenant(name='Other');db.add(other);db.flush()
    p=policy(db,user)
    p.tenant_id=other.id;db.commit()
    path=f'/api/v1/service/policies/{p.id}/indexes'
    assert c.get(path,headers=h).status_code==404
    assert c.post(path,headers=h).status_code==404
    user.role='viewer';db.commit()
    assert c.post(path,headers=h).status_code==403


def test_local_embedder_refuses_revision_and_truncation():
    from types import SimpleNamespace
    e=object.__new__(LocalEmbedder)
    e.revision='fixed'
    e.model=SimpleNamespace(tokenizer=lambda text,truncation:{'input_ids':[1,2,3]},max_seq_length=2)
    with pytest.raises(ValueError,match='revision'):e(['text'],'wrong')
    with pytest.raises(ValueError,match='token limit'):e(['text'],'fixed')


def test_worker_does_not_consume_other_revision_jobs(store):
    db,factory,user,_=store
    p=policy(db,user)
    old=enqueue(db,user.tenant_id,p.id,'old');db.commit()
    class NewEmbedder:
        revision='new'
        def __call__(self,*args):pytest.fail('Wrong revision executed')
    assert batch(factory,NewEmbedder())==[]
    db.refresh(old)
    assert old.status=='pending' and old.attempts==0


def test_empty_model_path_is_rejected_without_loading():
    with pytest.raises(ValueError,match='directory'):
        LocalEmbedder('', 'fixed')
