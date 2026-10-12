"""Tenant-scoped datasets, asynchronous experiments and persisted human scores."""
import copy
import json
from datetime import timedelta
from typing import Literal
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from .auth import current_user
from .business_agent import Strict
from .business_evaluation import CASES, evaluate, compare_reports
from .business_recovery import utcnow
from .config import settings
from .database import get_db, SessionLocal
from .models import ServiceDataset, ServiceExperiment, User
from .service_api import staff

router = APIRouter(prefix="/api/v1/service", tags=["Service experiments"])


class Case(Strict):
    id: str = Field(min_length=1, max_length=80)
    split: Literal["dev", "test"]
    category: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=4000)
    action: Literal["answer", "needs_information", "confirm_ticket"]
    order: str | None = Field(default=None, pattern=r"^A[0-9]{3}$")
    policy: Literal["refund-v1", "delivery-v1"] | None = None
    fact: str = Field(min_length=1, max_length=1000)


class DatasetInput(Strict):
    name: str = Field(min_length=2, max_length=120)
    cases: list[Case] = Field(min_length=1, max_length=24)


class ExperimentInput(Strict):
    dataset_id: str
    mode: Literal["mock", "openai"] = "mock"
    split: Literal["dev", "test"] = "dev"
    repeats: int = Field(default=1, ge=1, le=3)


class Score(Strict):
    revision: int = Field(ge=0)
    row: int = Field(ge=0)
    correct: bool | None
    notes: str = Field(default="", max_length=2000)


def owned_experiment(db, user, eid):
    item = db.scalar(select(ServiceExperiment).where(ServiceExperiment.id == eid, ServiceExperiment.tenant_id == user.tenant_id))
    if not item: raise HTTPException(404, "Experiment not found")
    return item


def output(e, full=True):
    return {"id":e.id,"dataset_id":e.dataset_id,"status":e.status,"config":{k:v for k,v in e.config.items() if k!="cases"},"report":e.report if full else {"metrics":e.report.get("metrics"),"progress":e.report.get("progress")},"error":e.error,"revision":e.revision,"created_at":e.created_at}


def execute_experiment(factory, eid):
    with factory() as db:
        claimed = db.execute(update(ServiceExperiment).where(ServiceExperiment.id == eid, ServiceExperiment.status == "pending").values(status="running")).rowcount
        db.commit()
        if not claimed: return
        config = copy.deepcopy(db.get(ServiceExperiment, eid).config)
    def progress(value):
        with factory() as db:
            changed = db.execute(update(ServiceExperiment).where(ServiceExperiment.id == eid, ServiceExperiment.status == "running").values(report={"progress":value})).rowcount
            db.commit()
            if not changed: raise RuntimeError("Experiment cancelled or expired")
    try:
        report = evaluate(mode=config["mode"],split=config["split"],repeats=config["repeats"],cases_override=config["cases"],on_progress=progress,model=config["model"])
        report["scope"] = "Isolated synthetic tool-runtime evaluation; does not use tenant catalogue or measure conversation-level performance."
        with factory() as db:
            db.execute(update(ServiceExperiment).where(ServiceExperiment.id == eid, ServiceExperiment.status == "running").values(status="completed",report=report)); db.commit()
    except Exception as exc:
        with factory() as db:
            db.execute(update(ServiceExperiment).where(ServiceExperiment.id == eid, ServiceExperiment.status == "running").values(status="failed",error=str(exc))); db.commit()


def dispatch(eid):
    if settings.execution_mode == "celery":
        from .worker import execute_experiment_task
        try: execute_experiment_task.apply_async(args=[eid],queue="evaluation")
        except Exception:
            with SessionLocal() as db:
                db.execute(update(ServiceExperiment).where(ServiceExperiment.id==eid,ServiceExperiment.status=="pending").values(status="failed",error="Queue unavailable; create a new experiment after recovery")); db.commit()
    else: execute_experiment(SessionLocal,eid)


def expire_experiments(factory):
    with factory() as db:
        db.execute(update(ServiceExperiment).where(ServiceExperiment.status.in_(["pending","running"]),ServiceExperiment.expires_at < utcnow()).values(status="failed",error="Experiment expired; no automatic paid replay. Start a new experiment explicitly.")); db.commit()


@router.get("/datasets")
def datasets(db: Session=Depends(get_db),user: User=Depends(current_user)):
    return [{"id":d.id,"name":d.name,"cases":d.cases,"created_at":d.created_at} for d in db.scalars(select(ServiceDataset).where(ServiceDataset.tenant_id==user.tenant_id).order_by(ServiceDataset.created_at.desc()))]


@router.post("/datasets/seed",status_code=201)
def seed_dataset(db: Session=Depends(get_db),user: User=Depends(current_user)):
    staff(user)
    d=ServiceDataset(tenant_id=user.tenant_id,name="售后工具标准集 v1",cases=json.loads(CASES.read_bytes()))
    db.add(d);db.commit()
    return {"id":d.id}


@router.post("/datasets",status_code=201)
def create_dataset(payload: DatasetInput,db: Session=Depends(get_db),user: User=Depends(current_user)):
    staff(user)
    if len({c.id for c in payload.cases}) != len(payload.cases): raise HTTPException(422,"Duplicate case IDs")
    if any(sum(c.split==split for c in payload.cases)>12 for split in ("dev","test")): raise HTTPException(422,"At most 12 cases per split")
    if any(c.action != "needs_information" and (not c.order or not c.policy) for c in payload.cases): raise HTTPException(422,"Answer and ticket cases require expected order and policy")
    d=ServiceDataset(tenant_id=user.tenant_id,name=payload.name,cases=[c.model_dump() for c in payload.cases]);db.add(d);db.commit()
    return {"id":d.id}


@router.get("/experiments")
def experiments(db: Session=Depends(get_db),user: User=Depends(current_user)):
    return [output(e,False) for e in db.scalars(select(ServiceExperiment).where(ServiceExperiment.tenant_id==user.tenant_id).order_by(ServiceExperiment.created_at.desc()).limit(50))]


@router.get("/experiments/{eid}")
def get_experiment(eid: str,db: Session=Depends(get_db),user: User=Depends(current_user)):
    return output(owned_experiment(db,user,eid))


@router.post("/experiments",status_code=202)
def create_experiment(payload: ExperimentInput,tasks: BackgroundTasks,db: Session=Depends(get_db),user: User=Depends(current_user)):
    staff(user)
    dataset=db.scalar(select(ServiceDataset).where(ServiceDataset.id==payload.dataset_id,ServiceDataset.tenant_id==user.tenant_id))
    if not dataset: raise HTTPException(404,"Dataset not found")
    if payload.mode=="openai" and not settings.openai_api_key: raise HTTPException(422,"Real model is not configured")
    count=sum(c["split"]==payload.split for c in dataset.cases)*payload.repeats
    if not count: raise HTTPException(422,"Selected split is empty")
    e=ServiceExperiment(tenant_id=user.tenant_id,dataset_id=dataset.id,config={**payload.model_dump(),"cases":copy.deepcopy(dataset.cases),"model":settings.openai_model if payload.mode=="openai" else "deterministic-demo"},expires_at=utcnow()+timedelta(seconds=count*130+300))
    db.add(e);db.commit();tasks.add_task(dispatch,e.id)
    return output(e)


@router.post("/experiments/{eid}/cancel")
def cancel(eid: str,db: Session=Depends(get_db),user: User=Depends(current_user)):
    staff(user);e=owned_experiment(db,user,eid)
    changed=db.execute(update(ServiceExperiment).where(ServiceExperiment.id==e.id,ServiceExperiment.status.in_(["pending","running"])).values(status="cancelled")).rowcount
    if not changed: raise HTTPException(409,"Experiment is already terminal")
    db.commit();db.refresh(e);return output(e)


@router.patch("/experiments/{eid}/scores")
def score(eid: str,payload: Score,db: Session=Depends(get_db),user: User=Depends(current_user)):
    staff(user);e=owned_experiment(db,user,eid)
    if e.status!="completed" or payload.row>=len(e.report.get("rows",[])):raise HTTPException(409,"No completed row to review")
    report=copy.deepcopy(e.report)
    report["rows"][payload.row]["human_review"].update(status="pending" if payload.correct is None else "reviewed",factual_correct=payload.correct,notes=payload.notes,reviewer_id=user.id,reviewed_at=utcnow().isoformat()+"Z")
    rows=report["rows"];pending=sum(r["human_review"]["factual_correct"] is None for r in rows)
    report["metrics"].update(human_review_pending=pending,semantic_success_rate=None if pending else sum(r["human_review"]["factual_correct"] is True for r in rows)/len(rows),end_to_end_success_rate=None if pending else sum(r["contract_pass"] and r["human_review"]["factual_correct"] is True for r in rows)/len(rows))
    changed=db.execute(update(ServiceExperiment).where(ServiceExperiment.id==eid,ServiceExperiment.revision==payload.revision).values(report=report,revision=ServiceExperiment.revision+1)).rowcount
    if not changed:raise HTTPException(409,"Review changed; refresh")
    db.commit();db.refresh(e);return output(e)


@router.get("/experiments/{eid}/compare/{baseline}")
def compare(eid: str,baseline: str,db: Session=Depends(get_db),user: User=Depends(current_user)):
    current=owned_experiment(db,user,eid);previous=owned_experiment(db,user,baseline)
    if current.status!="completed" or previous.status!="completed":raise HTTPException(409,"Both experiments must be completed")
    try:return compare_reports(current.report,previous.report)
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc
