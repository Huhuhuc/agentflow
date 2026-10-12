from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from fastapi import BackgroundTasks
from sqlalchemy import select,func
from test_business_reliability import disk
from test_agent import store,client
from app.models import AgentRun,AgentTicket,User
from app.service_api import Start,Revision,start,confirm
from app.service_catalogue import seed_catalogue
from app.business_agent import run_business
from app.config import settings,Settings
import pytest


def test_concurrent_task_approvals_return_same_ticket(disk):
    factory,_,uid=disk
    with factory() as db:
        user=db.get(User,uid);seed_catalogue(db,user.tenant_id)
        task=start(Start(text="A101退款请生成工单",request_key="concurrent-task"),BackgroundTasks(),db,user)
        tid=task["id"]
        run_business(db,db.get(AgentRun,task["run"]["id"]))
    barrier=Barrier(2)
    def approve():
        with factory() as db:
            user=db.get(User,uid);barrier.wait(timeout=5)
            return confirm(tid,Revision(revision=0),db,user)["ticket"]["id"]
    with ThreadPoolExecutor(2) as pool:
        futures=[pool.submit(approve) for _ in range(2)]
        assert len({future.result(timeout=10) for future in futures})==1
    with factory() as db:assert db.scalar(select(func.count()).select_from(AgentTicket))==1


def test_production_configuration_and_demo_login(client,store,monkeypatch):
    with pytest.raises(ValueError):Settings(_env_file=None,demo_mode=False,jwt_secret="short")
    assert Settings(_env_file=None,demo_mode=False,jwt_secret="x"*40).demo_mode is False
    c,h=client
    monkeypatch.setattr(settings,"demo_mode",False)
    assert c.get("/api/v1/auth/config").json()=={"demo_mode":False}
    assert c.post("/api/v1/auth/login",json={"email":"demo@agentflow.dev","password":"demo1234"}).status_code==401
    assert c.get("/api/v1/service/tasks",headers=h).status_code==200
    assert c.get("/health/ready").status_code==200
