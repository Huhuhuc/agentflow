"""Persistent single-order service conversations and audited ticket lifecycle."""
import copy
import hashlib
import json
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .agent_api import run_out, ticket_out
from .auth import current_user
from .business_agent import Strict, order_ids, ticket_requested, validate_order_policy
from .config import settings
from .database import get_db
from .models import AgentFeedback, AgentRun, AgentTicket, ServiceConversation, ServiceTask, ServiceTurn, ServiceAudit, ServiceTicketState, ServicePolicy, User
from .service_catalogue import catalogue_out, seed_catalogue, import_orders, add_policy, database_snapshot, lock_catalogue

router = APIRouter(prefix="/api/v1/service", tags=["Service conversations"])


class Start(Strict):
    text: str = Field(min_length=1, max_length=4000)
    mode: Literal["mock", "openai"] = "mock"
    request_key: str = Field(min_length=8, max_length=80)


class Reply(Strict):
    text: str = Field(min_length=1, max_length=4000)
    revision: int = Field(ge=0)
    request_key: str = Field(min_length=8, max_length=80)


class Revision(Strict):
    revision: int = Field(ge=0)


class Edit(Revision):
    title: str = Field(min_length=3, max_length=150)
    summary: str = Field(min_length=3, max_length=2000)


class TicketUpdate(Revision):
    status: Literal["open", "in_progress", "resolved"]
    note: str = Field(default="", max_length=2000)


class CSVImport(Strict):
    text: str = Field(min_length=1, max_length=300000)


class PolicyImport(Strict):
    slug: str = Field(pattern=r"^[a-z][a-z0-9-]{1,79}$")
    title: str = Field(min_length=2, max_length=150)
    text: str = Field(min_length=10, max_length=30000)
    topic: Literal["refund", "delivery"]
    order_status: Literal["delivered", "shipping"]
    effective_from: datetime | None = None


def staff(user):
    if user.role not in {"admin", "staff"}: raise HTTPException(403, "Staff role required")


def owned(db, user, task_id):
    item = db.scalar(select(ServiceTask).where(ServiceTask.id == task_id, ServiceTask.tenant_id == user.tenant_id))
    if not item: raise HTTPException(404, "Task not found")
    return item


def lock_task(db, task, revision):
    changed = db.execute(update(ServiceTask).where(ServiceTask.id == task.id, ServiceTask.revision == revision).values(revision=ServiceTask.revision + 1).execution_options(synchronize_session=False)).rowcount
    if not changed: raise HTTPException(409, "Task changed; refresh before retrying")
    db.refresh(task)


def audit(db, task, user, action, data=None):
    db.add(ServiceAudit(task_id=task.id, actor_id=user.id, action=action, data=data or {}))


def detail(db, task):
    conversation = db.get(ServiceConversation, task.conversation_id)
    turns = list(db.scalars(select(ServiceTurn).where(ServiceTurn.task_id == task.id).order_by(ServiceTurn.sequence)))
    run = db.get(AgentRun, task.latest_run_id) if task.latest_run_id else None
    ticket = db.scalar(select(AgentTicket).join(ServiceTicketState, ServiceTicketState.ticket_id == AgentTicket.id).where(ServiceTicketState.task_id == task.id))
    ticket_data = None
    if ticket:
        state = db.get(ServiceTicketState, ticket.id)
        ticket_data = {**ticket_out(ticket), "status": state.status, "note": state.note, "revision": state.revision}
    return {"id": task.id, "conversation_id": task.conversation_id, "title": conversation.title, "revision": task.revision,
            "context": task.context, "mode": task.mode, "status": "awaiting_input" if run and run.status == "needs_information" else run.status if run else "pending",
            "run": run_out(run) if run else None, "ticket": ticket_data,
            "messages": [{"sequence": t.sequence, "text": t.text, "run_id": t.run_id, "answer": db.get(AgentRun, t.run_id).result.get("summary", ""), "status": db.get(AgentRun, t.run_id).status} for t in turns],
            "audit": [{"action": a.action, "actor_id": a.actor_id, "data": a.data, "created_at": a.created_at} for a in db.scalars(select(ServiceAudit).where(ServiceAudit.task_id == task.id).order_by(ServiceAudit.created_at))]}


def create_turn(db, task, text, request_key):
    if not text.strip(): raise HTTPException(422, "Message cannot be blank")
    turns = list(db.scalars(select(ServiceTurn).where(ServiceTurn.task_id == task.id).order_by(ServiceTurn.sequence)))
    if len(turns) >= 40: raise HTTPException(422, "Conversation limit reached; start a new task")
    context = copy.deepcopy(task.context)
    ids = order_ids(text)
    if ids: context["order_ids"] = ids
    if any(w in text.lower() for w in ("退款", "退货", "refund", "申诉")): context["topic"] = "refund"
    elif any(w in text.lower() for w in ("物流", "配送", "送达", "delivery", "shipping")): context["topic"] = "delivery"
    if any(w in text for w in ("工单", "申诉")): context["ticket_requested"] = ticket_requested(text)
    snap = database_snapshot(db, task.tenant_id, text, task.mode)
    snap["context"] = context
    history = []
    for turn in turns[-8:]:
        history.append({"role": "user", "content": turn.text})
        previous = db.get(AgentRun, turn.run_id)
        if previous.result.get("summary"): history.append({"role": "assistant", "content": previous.result["summary"]})
    snap["conversation_messages"] = history
    feedback = AgentFeedback(tenant_id=task.tenant_id, text=text, version="service-v2")
    db.add(feedback); db.flush()
    run = AgentRun(tenant_id=task.tenant_id, feedback_id=feedback.id, snapshot=snap)
    db.add(run); db.flush()
    db.add(ServiceTurn(task_id=task.id, run_id=run.id, sequence=len(turns)+1, request_key=request_key, text=text))
    task.context, task.latest_run_id = context, run.id
    return run


def schedule(tasks, run_id):
    from .business_api import execute
    tasks.add_task(execute, run_id)


@router.get("/catalogue")
def catalogue(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return {**catalogue_out(db, user.tenant_id), "real_model_configured": bool(settings.openai_api_key), "role": user.role, "execution_mode": settings.execution_mode}


@router.post("/catalogue/seed")
def seed(db: Session = Depends(get_db), user: User = Depends(current_user)):
    staff(user); seed_catalogue(db, user.tenant_id)
    return catalogue_out(db, user.tenant_id)


@router.post("/orders/import")
def orders(payload: CSVImport, db: Session = Depends(get_db), user: User = Depends(current_user)):
    staff(user); return import_orders(db, user.tenant_id, payload.text)


@router.post("/policies", status_code=201)
def policies(payload: PolicyImport, db: Session = Depends(get_db), user: User = Depends(current_user)):
    staff(user); return add_policy(db, user.tenant_id, payload)


@router.post("/policies/{policy_id}/withdraw")
def withdraw(policy_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    staff(user)
    policy = db.scalar(select(ServicePolicy).where(ServicePolicy.id == policy_id, ServicePolicy.tenant_id == user.tenant_id))
    if not policy: raise HTTPException(404, "Policy not found")
    lock_catalogue(db, user.tenant_id); policy.active = False; db.commit()
    return {"withdrawn": policy.id}


@router.get("/tasks")
def listing(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(select(ServiceTask).where(ServiceTask.tenant_id == user.tenant_id).order_by(ServiceTask.created_at.desc()).limit(50))
    output = []
    for task in rows:
        run = db.get(AgentRun, task.latest_run_id)
        output.append({"id": task.id, "title": db.get(ServiceConversation, task.conversation_id).title, "status": "awaiting_input" if run.status == "needs_information" else run.status, "mode": task.mode})
    return output


@router.get("/tasks/{task_id}")
def get_task(task_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return detail(db, owned(db, user, task_id))


@router.post("/tasks", status_code=202)
def start(payload: Start, tasks: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(current_user)):
    digest = hashlib.sha256(json.dumps({"text": payload.text, "mode": payload.mode}, sort_keys=True).encode()).hexdigest()
    previous = db.scalar(select(ServiceTask).where(ServiceTask.tenant_id == user.tenant_id, ServiceTask.request_key == payload.request_key))
    if previous:
        if previous.request_hash != digest: raise HTTPException(409, "Idempotency key reused with different input")
        return detail(db, previous)
    if payload.mode == "openai" and not settings.openai_api_key: raise HTTPException(422, "Real model is not configured")
    conversation = ServiceConversation(tenant_id=user.tenant_id, title=payload.text[:150])
    db.add(conversation); db.flush()
    task = ServiceTask(tenant_id=user.tenant_id, conversation_id=conversation.id, request_key=payload.request_key, request_hash=digest, mode=payload.mode, context={})
    try:
        db.add(task); db.flush()
        run = create_turn(db, task, payload.text, payload.request_key)
        audit(db, task, user, "task_created")
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(ServiceTask).where(ServiceTask.tenant_id == user.tenant_id, ServiceTask.request_key == payload.request_key))
        if existing and existing.request_hash == digest: return detail(db, existing)
        raise HTTPException(409, "Idempotency conflict")
    schedule(tasks, run.id)
    return detail(db, task)


@router.post("/tasks/{task_id}/messages", status_code=202)
def reply(task_id: str, payload: Reply, tasks: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(current_user)):
    task = owned(db, user, task_id)
    prior = db.scalar(select(ServiceTurn).where(ServiceTurn.task_id == task.id, ServiceTurn.request_key == payload.request_key))
    if prior:
        if prior.text != payload.text: raise HTTPException(409, "Message key reused with different input")
        return detail(db, task)
    lock_task(db, task, payload.revision)
    old = db.get(AgentRun, task.latest_run_id)
    if old.status in {"pending", "running", "confirmed", "cancelled"}: raise HTTPException(409, "Task cannot accept a message in this state")
    if old.status == "awaiting_confirmation":
        changed = db.execute(update(AgentRun).where(AgentRun.id == old.id, AgentRun.status == "awaiting_confirmation").values(status="rejected")).rowcount
        if not changed: raise HTTPException(409, "Draft changed; refresh")
    run = create_turn(db, task, payload.text, payload.request_key)
    audit(db, task, user, "message_added", {"run_id": run.id}); db.commit()
    schedule(tasks, run.id)
    return detail(db, task)


@router.patch("/tasks/{task_id}/draft")
def edit(task_id: str, payload: Edit, db: Session = Depends(get_db), user: User = Depends(current_user)):
    staff(user); task = owned(db, user, task_id); lock_task(db, task, payload.revision)
    run = db.get(AgentRun, task.latest_run_id)
    if run.status != "awaiting_confirmation" or not run.result.get("draft"): raise HTTPException(409, "No editable draft")
    if len(payload.title.strip()) < 3 or len(payload.summary.strip()) < 3: raise HTTPException(422, "Draft must not be blank")
    result = copy.deepcopy(run.result); before = copy.deepcopy(result["draft"])
    result["draft"].update(title=payload.title.strip(), summary=payload.summary.strip())
    changed = db.execute(update(AgentRun).where(AgentRun.id == run.id, AgentRun.status == "awaiting_confirmation").values(result=result)).rowcount
    if not changed: raise HTTPException(409, "Draft is no longer editable")
    audit(db, task, user, "draft_edited", {"before": before, "after": result["draft"]}); db.commit()
    return detail(db, task)


@router.post("/tasks/{task_id}/confirm")
def confirm(task_id: str, payload: Revision, db: Session = Depends(get_db), user: User = Depends(current_user)):
    staff(user); task = owned(db, user, task_id)
    existing = db.scalar(select(ServiceTicketState).where(ServiceTicketState.task_id == task.id))
    if existing: return detail(db, task)
    try:
        lock_task(db, task, payload.revision)
    except HTTPException:
        db.rollback()
        if db.scalar(select(ServiceTicketState).where(ServiceTicketState.task_id == task.id)):
            db.refresh(task)
            return detail(db, task)
        raise
    run = db.get(AgentRun, task.latest_run_id)
    if run.status != "awaiting_confirmation" or not run.result.get("draft"): raise HTTPException(409, "No draft to confirm")
    # Serialize approval with catalogue updates; preserve exactly what was reviewed.
    lock_catalogue(db, user.tenant_id)
    fresh = database_snapshot(db, user.tenant_id, run.snapshot["input"]["text"], task.mode)
    fresh["context"] = run.snapshot.get("context", {})
    draft = run.result["draft"]
    oid = draft["order_id"]
    old_policies = {p["id"]: p for p in run.snapshot["knowledge"]}
    current_policies = {p["id"]: p for p in fresh["knowledge"]}
    refs = [r for r in draft["evidence_ids"] if r in old_policies]
    if fresh["orders"].get(oid) != run.snapshot["orders"].get(oid) or any(current_policies.get(r) != old_policies[r] for r in refs):
        raise HTTPException(409, "Order or policy changed. Send a follow-up message to refresh evidence before approval.")
    try: validate_order_policy(draft["evidence_ids"], fresh)
    except ValueError as exc: raise HTTPException(409, str(exc)) from exc
    changed = db.execute(update(AgentRun).where(AgentRun.id == run.id, AgentRun.status == "awaiting_confirmation").values(status="confirmed")).rowcount
    if not changed: raise HTTPException(409, "Draft changed; refresh")
    ticket = AgentTicket(tenant_id=user.tenant_id, run_id=run.id, confirmed_by=user.id, draft=draft)
    db.add(ticket); db.flush()
    db.add(ServiceTicketState(ticket_id=ticket.id, task_id=task.id))
    audit(db, task, user, "ticket_created", {"ticket_id": ticket.id, "draft": draft}); db.commit()
    return detail(db, task)


@router.patch("/tasks/{task_id}/ticket")
def update_ticket(task_id: str, payload: TicketUpdate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    staff(user); task = owned(db, user, task_id)
    state = db.scalar(select(ServiceTicketState).where(ServiceTicketState.task_id == task.id))
    if not state: raise HTTPException(404, "Ticket not found")
    if payload.status == "resolved" and not payload.note.strip(): raise HTTPException(422, "Resolution note required")
    changed = db.execute(update(ServiceTicketState).where(ServiceTicketState.ticket_id == state.ticket_id, ServiceTicketState.revision == payload.revision).values(status=payload.status, note=payload.note, revision=ServiceTicketState.revision + 1)).rowcount
    if not changed: raise HTTPException(409, "Ticket changed; refresh")
    audit(db, task, user, "ticket_updated", {"status": payload.status, "note": payload.note}); db.commit()
    return detail(db, task)


@router.post("/tasks/{task_id}/{action}")
def transition(task_id: str, action: str, payload: Revision, tasks: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(current_user)):
    task = owned(db, user, task_id); lock_task(db, task, payload.revision)
    states = {"cancel": ({"pending", "running", "awaiting_confirmation", "needs_information", "failed", "completed"}, "cancelled"), "reject": ({"awaiting_confirmation"}, "rejected"), "resume": ({"failed"}, "pending")}
    if action not in states: raise HTTPException(404, "Unknown action")
    allowed, target = states[action]
    changed = db.execute(update(AgentRun).where(AgentRun.id == task.latest_run_id, AgentRun.status.in_(allowed)).values(status=target)).rowcount
    if not changed: raise HTTPException(409, "Action is not valid for this state")
    audit(db, task, user, action); db.commit()
    if action == "resume": schedule(tasks, task.latest_run_id)
    return detail(db, task)
