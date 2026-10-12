import copy
import uuid
from datetime import timedelta
from sqlalchemy import select, update
from test_agent import store, client
from app.business_recovery import utcnow
from app.business_queue import enqueue
from app.models import AgentRun, BusinessDispatch, ServiceExperiment, ServiceDataset
from app.service_experiments import execute_experiment, expire_experiments
from app.config import settings


def test_dataset_experiment_review_and_comparison(client,store,monkeypatch):
    monkeypatch.setattr("app.service_experiments.SessionLocal",store[1])
    c,h=client
    dataset=c.post("/api/v1/service/datasets/seed",headers=h).json()["id"]
    payload={"dataset_id":dataset,"mode":"mock","split":"dev","repeats":1}
    first=c.post("/api/v1/service/experiments",headers=h,json=payload)
    assert first.status_code==202,first.text
    eid=first.json()["id"]
    report=c.get("/api/v1/service/experiments/"+eid,headers=h).json()
    assert report["status"]=="completed" and report["report"]["metrics"]["cases"]==12
    assert report["report"]["metrics"]["semantic_success_rate"] is None
    scored=c.patch("/api/v1/service/experiments/"+eid+"/scores",headers=h,json={"revision":0,"row":0,"correct":False,"notes":"人工判定该样本内容不完整"})
    assert scored.status_code==200 and scored.json()["report"]["rows"][0]["human_review"]["factual_correct"] is False
    assert c.patch("/api/v1/service/experiments/"+eid+"/scores",headers=h,json={"revision":0,"row":0,"correct":True,"notes":""}).status_code==409
    second=c.post("/api/v1/service/experiments",headers=h,json=payload).json()["id"]
    compare=c.get("/api/v1/service/experiments/"+second+"/compare/"+eid,headers=h)
    assert compare.status_code==200 and compare.json()["metric_deltas"]["contract_pass_rate"]==0
    monkeypatch.setattr(settings,"openai_api_key","")
    assert c.post("/api/v1/service/experiments",headers=h,json={**payload,"mode":"openai"}).status_code==422
    # Changing the dataset creates a new immutable dataset and mismatched comparisons fail.
    cases=copy.deepcopy(c.get("/api/v1/service/datasets",headers=h).json()[0]["cases"])
    cases[0]["text"]="另一条独立业务问题 A101 退款"
    new=c.post("/api/v1/service/datasets",headers=h,json={"name":"独立数据集","cases":cases})
    assert new.status_code==201
    third=c.post("/api/v1/service/experiments",headers=h,json={**payload,"dataset_id":new.json()["id"]}).json()["id"]
    assert c.get("/api/v1/service/experiments/"+third+"/compare/"+eid,headers=h).status_code==422


def test_expired_experiment_is_not_automatically_replayed(store):
    db,factory,user,_=store
    dataset=ServiceDataset(tenant_id=user.tenant_id,name="test",cases=[]);db.add(dataset);db.flush()
    e=ServiceExperiment(tenant_id=user.tenant_id,dataset_id=dataset.id,status="running",config={},expires_at=utcnow()-timedelta(seconds=1))
    db.add(e);db.commit()
    expire_experiments(factory);db.refresh(e)
    assert e.status=="failed" and "no automatic paid replay" in e.error


def test_dispatch_failure_remains_pending_and_retries_once_due(store,monkeypatch):
    from app.business_agent import snapshot
    db,factory,user,feedback=store
    run=AgentRun(tenant_id=user.tenant_id,feedback_id=feedback.id,snapshot=snapshot("A101退款","mock"));db.add(run);db.commit()
    def unavailable(**_):raise RuntimeError("broker down")
    monkeypatch.setattr("app.worker.execute_business_task.apply_async",unavailable)
    assert not enqueue(factory,run.id)
    db.refresh(run);assert run.status=="pending"
    dispatch=db.get(BusinessDispatch,run.id)
    assert dispatch.attempts==1 and dispatch.last_error=="RuntimeError"
    assert not enqueue(factory,run.id)
    sent=[]
    monkeypatch.setattr("app.worker.execute_business_task.apply_async",lambda **kw:sent.append(kw))
    dispatch.next_attempt_at=utcnow()-timedelta(seconds=1);db.commit()
    assert enqueue(factory,run.id)
    assert sent==[{"args":[run.id],"queue":"business"}]
    db.refresh(dispatch);assert dispatch.attempts==2 and dispatch.last_error is None


def test_experiment_cancel_fences_final_report(store,monkeypatch):
    db,factory,user,_=store
    dataset=ServiceDataset(tenant_id=user.tenant_id,name="test",cases=[]);db.add(dataset);db.flush()
    e=ServiceExperiment(tenant_id=user.tenant_id,dataset_id=dataset.id,config={"mode":"mock","split":"dev","repeats":1,"cases":[],"model":"demo"},expires_at=utcnow()+timedelta(minutes=5))
    db.add(e);db.commit()
    def cancelled(**kwargs):
        with factory() as other:other.execute(update(ServiceExperiment).where(ServiceExperiment.id==e.id).values(status="cancelled"));other.commit()
        kwargs["on_progress"]({"completed":1,"total":1})
    monkeypatch.setattr("app.service_experiments.evaluate",cancelled)
    execute_experiment(factory,e.id);db.refresh(e)
    assert e.status=="cancelled" and e.report=={}
