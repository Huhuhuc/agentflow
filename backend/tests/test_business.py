import pytest
from test_agent import store, client
from app.business_agent import snapshot, run_business, invoke
from app.models import AgentRun, AgentTicket
from sqlalchemy import select

def task(store, text):
    db, _, user, feedback = store
    run = AgentRun(tenant_id=user.tenant_id, feedback_id=feedback.id, snapshot=snapshot(text, 'mock'))
    db.add(run); db.commit()
    return run

@pytest.mark.parametrize('text,status', [
    ('A101 退款条件是什么','completed'), ('A102 退款请生成申诉工单','awaiting_confirmation'),
    ('A103 配送逾期请创建工单','awaiting_confirmation'), ('A999 退款','needs_information'),
    ('退款如何办理','needs_information'), ('A101 不存在的政策','needs_information'),
])
def test_business_cases(store, text, status):
    db = store[0]
    run = run_business(db, task(store,text))
    assert run.status == status
    assert not db.scalar(select(AgentTicket))
    assert run.token_used == 0

def test_draft_cannot_invent_evidence():
    with pytest.raises(ValueError):
        invoke('draft_ticket', {'order_id':'A102','title':'test','summary':'test','evidence_ids':['order-A102','refund-v1']},snapshot('A102退款','mock'),{})

def test_resume_uses_persisted_tool_results(store):
    from app.business_agent import mock_turn
    run = task(store,'A102退款请创建工单')
    count=0
    def failure(messages,snap):
        nonlocal count
        count+=1
        if count==2: raise RuntimeError('simulated provider outage')
        return mock_turn(messages,snap)
    run_business(store[0],run,failure)
    assert run.status=='failed' and run.result['checkpoint']['step']==1
    run_business(store[0],run)
    assert run.status=='awaiting_confirmation'
    assert len([t for t in run.trace if t.get('name')=='get_order'])==1

def test_real_adapter_contract_and_budget(store):
    run=task(store,'A102退款')
    run_business(store[0],run,lambda *_:{'tokens':12001,'result':{}})
    assert run.status=='failed' and 'Token' in run.error_message
    run=task(store,'A102退款')
    run_business(store[0],run,lambda *_:{'result':{'summary':'未知证据回答','evidence_ids':['fake'],'next_action':'answer'}})
    assert run.status=='failed'

def test_api_confirm_reject_and_isolation(client,store,monkeypatch):
    import app.business_api as module
    monkeypatch.setattr(module,'SessionLocal',store[1])
    c,h=client
    assert c.get('/api/v1/business/catalogue',headers=h).status_code==200
    r=c.post('/api/v1/business/runs',headers=h,json={'text':'A102退款请创建工单'})
    assert r.status_code==202
    rid=r.json()['id']
    a=c.post(f'/api/v1/business/runs/{rid}/confirm',headers=h)
    b=c.post(f'/api/v1/business/runs/{rid}/confirm',headers=h)
    assert a.status_code==200 and a.json()['id']==b.json()['id']
    assert c.post(f'/api/v1/business/runs/{rid}/cancel',headers=h).status_code==409
    r=c.post('/api/v1/business/runs',headers=h,json={'text':'A103配送请创建工单'}).json()
    assert c.post(f"/api/v1/business/runs/{r['id']}/reject",headers=h).status_code==200
    assert c.post(f"/api/v1/business/runs/{r['id']}/confirm",headers=h).status_code==409
    assert c.get('/api/v1/business/runs').status_code==401

def test_tenant_cannot_access_or_cancel_business_run(client,store,monkeypatch):
    from app.models import Tenant, User
    from app.auth import create_token
    monkeypatch.setattr('app.business_api.SessionLocal',store[1])
    c,h=client
    rid=c.post('/api/v1/business/runs',headers=h,json={'text':'A102退款请创建工单'}).json()['id']
    db=store[0]
    tenant=Tenant(name='Other business');db.add(tenant);db.flush()
    user=User(tenant_id=tenant.id,email='biz-other@test.dev',name='Other',password_hash='unused');db.add(user);db.commit()
    headers={'Authorization':f'Bearer {create_token(user)}'}
    assert c.get('/api/v1/business/runs',headers=headers).json()==[]
    for action in ('confirm','cancel','resume'):
        assert c.post(f'/api/v1/business/runs/{rid}/{action}',headers=headers).status_code==404
    assert c.post(f'/api/v1/business/runs/{rid}/cancel',headers=h).status_code==200
    assert c.post(f'/api/v1/business/runs/{rid}/confirm',headers=h).status_code==409
