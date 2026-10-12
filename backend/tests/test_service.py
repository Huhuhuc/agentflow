import uuid
from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import select
from test_agent import store, client
from app.auth import create_token
from app.models import Tenant, User, ServiceTurn, ServiceOrder


@pytest.fixture
def service(client, store, monkeypatch):
    monkeypatch.setattr("app.business_api.SessionLocal", store[1])
    c, h = client
    assert c.post("/api/v1/service/catalogue/seed", headers=h).status_code == 200
    return c, h


def start(service, text="我要退款", key=None):
    c, h = service
    response = c.post("/api/v1/service/tasks", headers=h, json={"text": text, "mode": "mock", "request_key": key or str(uuid.uuid4())})
    assert response.status_code == 202, response.text
    return c.get("/api/v1/service/tasks/" + response.json()["id"], headers=h).json()


def reply(service, task, text):
    c, h = service
    r = c.post("/api/v1/service/tasks/" + task["id"] + "/messages", headers=h, json={"text":text,"revision":task["revision"],"request_key":str(uuid.uuid4())})
    assert r.status_code == 202, r.text
    return c.get("/api/v1/service/tasks/" + task["id"], headers=h).json()


def test_conversation_edit_approve_and_ticket_lifecycle(service, store):
    c, h = service
    task = start(service)
    assert task["status"] == "awaiting_input"
    cid = task["conversation_id"]
    task = reply(service, task, "A102")
    assert task["status"] == "completed"
    task = reply(service, task, "请生成工单，注明商品有质量问题")
    assert task["status"] == "awaiting_confirmation" and task["conversation_id"] == cid
    assert len(task["messages"]) == 3
    path = "/api/v1/service/tasks/" + task["id"]
    r = c.patch(path+"/draft",headers=h,json={"revision":task["revision"],"title":"质量问题人工审核","summary":"顾客说明商品质量存在问题，请客服核实照片和订单信息。"})
    assert r.status_code == 200, r.text
    task = r.json()
    assert c.post("/api/v1/business/runs/"+task["run"]["id"]+"/confirm",headers=h).status_code == 409
    r = c.post(path+"/confirm",headers=h,json={"revision":task["revision"]})
    assert r.status_code == 200, r.text
    ticket = r.json()["ticket"]
    assert ticket["draft"]["title"] == "质量问题人工审核"
    assert c.post(path+"/confirm",headers=h,json={"revision":0}).json()["ticket"]["id"] == ticket["id"]
    r = c.patch(path+"/ticket",headers=h,json={"revision":0,"status":"resolved","note":"客服已核实并记录处理结果"})
    assert r.status_code == 200 and r.json()["ticket"]["status"] == "resolved"
    assert c.patch(path+"/ticket",headers=h,json={"revision":0,"status":"open","note":""}).status_code == 409
    assert len(r.json()["audit"]) >= 6


def test_idempotent_creation_and_stale_messages(service, store):
    c, h = service
    key = str(uuid.uuid4())
    one, two = start(service, key=key), start(service, key=key)
    assert one["id"] == two["id"]
    assert c.post("/api/v1/service/tasks",headers=h,json={"text":"不同任务","request_key":key}).status_code == 409
    path = "/api/v1/service/tasks/"+one["id"]+"/messages"
    payload = {"text":"A101","revision":0,"request_key":str(uuid.uuid4())}
    first = c.post(path,headers=h,json=payload)
    second = c.post(path,headers=h,json=payload)
    assert first.status_code == second.status_code == 202
    assert len(second.json()["messages"]) == 2
    payload["request_key"] = str(uuid.uuid4())
    assert c.post(path,headers=h,json=payload).status_code == 409


def test_csv_atomic_import_and_stale_order_approval(service):
    c, h = service
    path = "/api/v1/service/orders/import"
    bad = "id,status,amount,days_since_delivery,used\nA201,delivered,199,3,false\nA202,bad,99,2,false"
    assert c.post(path,headers=h,json={"text":bad}).status_code == 422
    assert all(o["id"] != "A201" for o in c.get("/api/v1/service/catalogue",headers=h).json()["orders"])
    task = start(service,"A101退款请创建工单")
    good = "id,status,amount,days_since_delivery,used\nA101,delivered,199,12,true"
    assert c.post(path,headers=h,json={"text":good}).status_code == 200
    assert c.post("/api/v1/service/tasks/"+task["id"]+"/confirm",headers=h,json={"revision":task["revision"]}).status_code == 409
    task = reply(service,task,"请按最新信息重新核对")
    assert task["status"] == "awaiting_confirmation"
    assert c.post("/api/v1/service/tasks/"+task["id"]+"/confirm",headers=h,json={"revision":task["revision"]}).status_code == 200


def test_policy_versions_future_and_withdrawal(service):
    c, h = service
    task = start(service,"A102退款请生成工单")
    policy = {"slug":"refund","title":"退款新规则","topic":"refund","order_status":"delivered","text":"新版本规则：所有退款申请均需提供购买证明，由客服人工审核。"}
    future = (datetime.now(timezone.utc)+timedelta(days=3)).isoformat()
    r = c.post("/api/v1/service/policies",headers=h,json={**policy,"effective_from":future})
    assert r.status_code == 201 and r.json()["version"] == 2
    # A not-yet-effective version does not invalidate current evidence.
    assert c.post("/api/v1/service/tasks/"+task["id"]+"/confirm",headers=h,json={"revision":task["revision"]}).status_code == 200
    task = start(service,"A101退款请生成工单")
    r = c.post("/api/v1/service/policies",headers=h,json=policy)
    assert r.status_code == 201 and r.json()["version"] == 3
    assert c.post("/api/v1/service/tasks/"+task["id"]+"/confirm",headers=h,json={"revision":task["revision"]}).status_code == 409
    task = reply(service,task,"请使用最新退款政策")
    assert any("@3#" in e["id"] for e in task["run"]["result"]["evidence"])
    assert c.post("/api/v1/service/policies/"+r.json()["id"]+"/withdraw",headers=h).status_code == 200
    task = start(service,"A101退款")
    assert task["status"] == "awaiting_input"


def test_tenant_and_role_boundaries(service, store):
    c, h = service
    task = start(service,"A102退款请生成工单")
    db = store[0]
    tenant = Tenant(name="Other"); db.add(tenant); db.flush()
    other = User(tenant_id=tenant.id,email="other-service@test.dev",name="Other",password_hash="unused",role="admin")
    viewer = User(tenant_id=store[2].tenant_id,email="viewer@test.dev",name="Viewer",password_hash="unused",role="viewer")
    db.add_all([other,viewer]); db.commit()
    oh = {"Authorization":"Bearer "+create_token(other)}
    vh = {"Authorization":"Bearer "+create_token(viewer)}
    assert c.get("/api/v1/service/tasks",headers=oh).json() == []
    assert c.get("/api/v1/service/catalogue",headers=oh).json()["orders"] == []
    assert c.get("/api/v1/service/tasks/"+task["id"],headers=oh).status_code == 404
    assert c.post("/api/v1/service/tasks/"+task["id"]+"/confirm",headers=vh,json={"revision":0}).status_code == 403
    assert c.post("/api/v1/service/catalogue/seed",headers=vh).status_code == 403
