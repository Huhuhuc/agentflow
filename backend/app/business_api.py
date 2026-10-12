from typing import Literal
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from .agent_api import owned_run, run_out, confirm, ticket_out
from .auth import current_user
from .business_agent import Strict, snapshot, run_business, POLICIES, ORDERS
from .config import settings
from .database import SessionLocal, get_db
from .models import AgentFeedback, AgentRun, AgentTicket, User, ServiceTurn

router = APIRouter(prefix="/api/v1/business", tags=["Enterprise service agent"])

class Request(Strict):
    text: str = Field(min_length=3, max_length=4000)
    mode: Literal["mock", "openai"] = "mock"

def business_run(run_id, db, user):
    run = owned_run(run_id, db, user)
    if run.snapshot.get("runtime_version") != "business-agent-v1": raise HTTPException(404, "Run not found")
    return run

def execute(run_id):
    if settings.execution_mode == "celery":
        from .business_queue import enqueue
        enqueue(SessionLocal, run_id)
        return
    from .business_recovery import claim
    with SessionLocal() as db:
        token = claim(db, run_id)
        if token: run_business(db, db.get(AgentRun, run_id), lease_token=token)

@router.get("/catalogue")
def catalogue(user: User = Depends(current_user)):
    return {"policies": POLICIES, "orders": list(ORDERS.values()), "synthetic": True, "real_model_configured": bool(settings.openai_api_key)}

@router.post("/runs", status_code=202)
def create(payload: Request, tasks: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if len(payload.text.strip()) < 3: raise HTTPException(422, "Enter a task")
    if payload.mode == "openai" and not settings.openai_api_key: raise HTTPException(422, "Real model is not configured")
    feedback = AgentFeedback(tenant_id=user.tenant_id, text=payload.text.strip(), version="business-v1")
    db.add(feedback); db.flush()
    run = AgentRun(tenant_id=user.tenant_id, feedback_id=feedback.id, snapshot=snapshot(feedback.text, payload.mode))
    db.add(run); db.commit(); db.refresh(run)
    tasks.add_task(execute, run.id)
    return run_out(run)

@router.get("/runs")
def listing(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(select(AgentRun).where(AgentRun.tenant_id == user.tenant_id).order_by(AgentRun.created_at.desc()))
    return [run_out(r) for r in rows if r.snapshot.get("runtime_version") == "business-agent-v1"][:100]

@router.post("/runs/{run_id}/confirm")
def accept(run_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    run = business_run(run_id, db, user)
    if db.scalar(select(ServiceTurn.id).where(ServiceTurn.run_id == run_id)):
        raise HTTPException(409, "Use the service task approval endpoint for version checks and audit")
    existing = db.scalar(select(AgentTicket).where(AgentTicket.run_id == run.id))
    if existing: return ticket_out(existing)
    if not run.result.get("draft"): raise HTTPException(409, "No draft to confirm")
    claimed = db.execute(update(AgentRun).where(AgentRun.id == run.id, AgentRun.status == "awaiting_confirmation").values(status="confirmed")).rowcount
    if not claimed:
        db.rollback()
        existing = db.scalar(select(AgentTicket).where(AgentTicket.run_id == run.id))
        if existing: return ticket_out(existing)
        raise HTTPException(409, "Run cannot be confirmed")
    ticket = AgentTicket(tenant_id=user.tenant_id, run_id=run.id, confirmed_by=user.id, draft=run.result["draft"])
    db.add(ticket); db.commit(); db.refresh(ticket)
    return ticket_out(ticket)

@router.post("/runs/{run_id}/{action}")
def transition(run_id: str, action: str, tasks: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(current_user)):
    run = business_run(run_id, db, user)
    if db.scalar(select(ServiceTurn.id).where(ServiceTurn.run_id == run_id)):
        raise HTTPException(409, "Use the service task endpoint")
    states = {"cancel": ({"pending", "running", "awaiting_confirmation"}, "cancelled"), "reject": ({"awaiting_confirmation"}, "rejected"), "resume": ({"failed"}, "pending")}
    if action not in states: raise HTTPException(404, "Unknown action")
    allowed, target = states[action]
    changed = db.execute(update(AgentRun).where(AgentRun.id == run.id, AgentRun.status.in_(allowed)).values(status=target)).rowcount
    if not changed: raise HTTPException(409, "Action is not valid for this state")
    db.commit(); db.refresh(run)
    if action == "resume": tasks.add_task(execute, run.id)
    return run_out(run)

@router.get("/tickets")
def tickets(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.execute(select(AgentTicket, AgentRun).join(AgentRun, AgentTicket.run_id == AgentRun.id).where(AgentTicket.tenant_id == user.tenant_id))
    return [ticket_out(t) for t, r in rows if r.snapshot.get("runtime_version") == "business-agent-v1"]
