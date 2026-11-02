from datetime import datetime, timedelta
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.models import Tenant, ServicePolicy, PolicyIndex
from app.policy_index import enqueue, claim, finish, retry, run, split_text


@pytest.fixture
def indexed(tmp_path):
    engine = create_engine('sqlite:///'+str(tmp_path/'index.db'))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        tenant = Tenant(name='Index tenant'); db.add(tenant); db.flush()
        policy = ServicePolicy(tenant_id=tenant.id, slug='refund', version=1, title='Refund',
            text='退款政策。'*150, topic='refund', order_status='delivered')
        db.add(policy); db.flush()
        item = enqueue(db, tenant.id, policy.id, 'test-vectors@fixed'); db.commit()
        yield factory, tenant.id, policy.id, item.id
    engine.dispose()


def test_offsets_cover_source():
    text='中文条款 abc '*100
    chunks=split_text(text)
    assert chunks[0]['start']==0 and chunks[-1]['end']==len(text)
    assert all(c['text']==text[c['start']:c['end']] for c in chunks)
    assert all(a['end']>=b['start'] for a,b in zip(chunks,chunks[1:]))


def test_idempotent_and_revision_isolated(indexed):
    factory,tenant,policy,ident=indexed
    with factory() as db:
        assert enqueue(db,tenant,policy,'test-vectors@fixed').id==ident
        assert enqueue(db,tenant,policy,'new-revision').id!=ident
        with pytest.raises(LookupError):enqueue(db,'other',policy,'test')


def test_claim_once_and_old_worker_fenced(indexed):
    factory,tenant,_,ident=indexed
    now=datetime.utcnow()
    with factory() as db:
        first=claim(db,tenant,ident,now)
        assert first and claim(db,tenant,ident,now) is None
        second=claim(db,tenant,ident,now+timedelta(seconds=121))
        assert second and second!=first
        assert not finish(db,tenant,ident,first,error='Stale',now=now+timedelta(seconds=122))
        assert finish(db,tenant,ident,second,error='TimeoutError',now=now+timedelta(seconds=122))


def test_atomic_ready_and_tenant_boundary(indexed):
    factory,tenant,_,ident=indexed
    assert not run(factory,'other',ident,lambda *_:pytest.fail('Must not invoke'))
    assert run(factory,tenant,ident,lambda texts,revision:[[3,4] for _ in texts])
    with factory() as db:
        item=db.get(PolicyIndex,ident)
        assert item.status=='ready' and item.vectors==[[.6,.8]]*len(item.chunks)
        assert not retry(db,tenant,ident)


@pytest.mark.parametrize('vector',[[0,0],[float('nan'),1],[True,1]])
def test_bad_embedding_never_published(indexed,vector):
    factory,tenant,_,ident=indexed
    assert not run(factory,tenant,ident,lambda texts,_:[vector for _ in texts])
    with factory() as db:
        item=db.get(PolicyIndex,ident)
        assert item.status=='failed' and item.vectors==[]
        assert not retry(db,'other',ident)
        assert retry(db,tenant,ident)


def test_retry_budget(indexed):
    factory,tenant,_,ident=indexed
    def unavailable(*_):raise TimeoutError('service unavailable')
    for attempt in range(3):
        assert not run(factory,tenant,ident,unavailable)
        with factory() as db:assert retry(db,tenant,ident)==(attempt<2)
    with factory() as db:assert db.get(PolicyIndex,ident).attempts==3


def test_crashed_final_attempt_becomes_failed(indexed):
    factory,tenant,_,ident=indexed
    now=datetime.utcnow()
    with factory() as db:
        for offset in (0,121,242):assert claim(db,tenant,ident,now+timedelta(seconds=offset))
        assert claim(db,tenant,ident,now+timedelta(seconds=363)) is None
        db.expire_all()
        assert db.get(PolicyIndex,ident).error=='LeaseAttemptsExhausted'
