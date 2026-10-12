from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .agent_runtime import make_snapshot, run_agent
from .agent_schemas import FeedbackCreate, RunCreate
from .agent_tools import RELEASE_NOTES, tool_definitions
from .auth import current_user
from .config import settings
from .database import SessionLocal, get_db
from .models import AgentFeedback, AgentRun, AgentTicket, User

router = APIRouter(prefix="/api/v1/agent", tags=["Feedback Agent"])


def feedback_out(item: AgentFeedback) -> dict:
    return {"id": item.id, "text": item.text, "version": item.version, "created_at": item.created_at}


def ticket_out(item: AgentTicket) -> dict:
    return {"id": item.id, "run_id": item.run_id, "draft": item.draft, "created_at": item.created_at}


def run_out(item: AgentRun) -> dict:
    return {"id": item.id, "feedback_id": item.feedback_id, "status": item.status, "snapshot": item.snapshot, "trace": item.trace, "result": item.result, "error_message": item.error_message, "token_used": item.token_used, "duration_ms": item.duration_ms, "created_at": item.created_at}


def owned_run(run_id: str, db: Session, user: User) -> AgentRun:
    run = db.scalar(select(AgentRun).where(AgentRun.id == run_id, AgentRun.tenant_id == user.tenant_id))
    if not run:
        raise HTTPException(404, "Run not found")
    return run


def execute_agent_background(run_id: str):
    with SessionLocal() as db:
        run = db.get(AgentRun, run_id)
        if run and run.status == "pending":
            run_agent(db, run)


@router.get("/capabilities")
def capabilities(_: User = Depends(current_user)):
    return {"real_model_configured": bool(settings.openai_api_key), "tools": tool_definitions(), "knowledge": RELEASE_NOTES, "knowledge_type": "retained synthetic demo notes; lexical retrieval", "external_ticketing": False}


@router.get("/feedbacks")
def feedbacks(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return [feedback_out(f) for f in db.scalars(select(AgentFeedback).where(AgentFeedback.tenant_id == user.tenant_id).order_by(AgentFeedback.created_at.desc()).limit(100))]


@router.post("/feedbacks", status_code=201)
def create_feedback(payload: FeedbackCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if len(payload.text.strip()) < 3 or not payload.version.strip():
        raise HTTPException(422, "Feedback text and version must not be blank")
    feedback = AgentFeedback(tenant_id=user.tenant_id, text=payload.text.strip(), version=payload.version.strip())
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    return feedback_out(feedback)


@router.post("/runs", status_code=202)
def create_run(payload: RunCreate, tasks: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(current_user)):
    feedback = db.scalar(select(AgentFeedback).where(AgentFeedback.id == payload.feedback_id, AgentFeedback.tenant_id == user.tenant_id))
    if not feedback:
        raise HTTPException(404, "Feedback not found")
    if payload.mode == "openai" and not settings.openai_api_key:
        raise HTTPException(422, "Configure OPENAI_API_KEY before selecting real model mode")
    run = AgentRun(tenant_id=user.tenant_id, feedback_id=feedback.id, snapshot=make_snapshot(feedback.text, feedback.version, payload.mode))
    db.add(run)
    db.commit()
    db.refresh(run)
    tasks.add_task(execute_agent_background, run.id)
    return run_out(run)


@router.get("/runs")
def runs(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return [run_out(r) for r in db.scalars(select(AgentRun).where(AgentRun.tenant_id == user.tenant_id).order_by(AgentRun.created_at.desc()).limit(50))]


@router.get("/runs/{run_id}")
def run_detail(run_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return run_out(owned_run(run_id, db, user))


@router.post("/runs/{run_id}/confirm")
def confirm(run_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    run = owned_run(run_id, db, user)
    existing = db.scalar(select(AgentTicket).where(AgentTicket.run_id == run.id, AgentTicket.tenant_id == user.tenant_id))
    if existing:
        return ticket_out(existing)
    if run.status != "awaiting_confirmation" or not run.result.get("draft"):
        raise HTTPException(409, "Only a completed evidence-backed draft can be confirmed")
    ticket = AgentTicket(tenant_id=user.tenant_id, run_id=run.id, confirmed_by=user.id, draft=run.result["draft"])
    db.add(ticket)
    run.status = "confirmed"
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        ticket = db.scalar(select(AgentTicket).where(AgentTicket.run_id == run.id, AgentTicket.tenant_id == user.tenant_id))
        if not ticket:
            raise HTTPException(409, "Confirmation conflict")
    db.refresh(ticket)
    return ticket_out(ticket)


@router.get("/tickets")
def tickets(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return [ticket_out(t) for t in db.scalars(select(AgentTicket).where(AgentTicket.tenant_id == user.tenant_id).order_by(AgentTicket.created_at.desc()).limit(100))]


@router.get("/evaluation")
def evaluation(_: User = Depends(current_user)):
    from .agent_evaluation import evaluate
    return evaluate(mode="mock")
