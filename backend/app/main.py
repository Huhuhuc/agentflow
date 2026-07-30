from contextlib import asynccontextmanager

import asyncio
import json

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import create_token, current_user, verify_password
from .config import settings
from .database import Base, SessionLocal, engine, get_db
from .engine import execute_graph, validate_graph
from .models import Execution, Template, User, Workflow, WorkflowVersion
from .schemas import ExecutionLogOut, ExecutionOut, ExecutionRequest, LoginRequest, TokenResponse, UserOut, WorkflowCreate, WorkflowOut, WorkflowUpdate
from .seed import seed
from .worker import execute_workflow_task


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed(db)
    yield


app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins.split(","), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.get("/health/live")
def live():
    return {"status": "ok"}


@app.post("/api/v1/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == payload.email))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Invalid credentials")
    return TokenResponse(access_token=create_token(user))


@app.get("/api/v1/auth/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


@app.get("/api/v1/workflows", response_model=list[WorkflowOut])
def workflows(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return list(db.scalars(select(Workflow).where(Workflow.tenant_id == user.tenant_id).order_by(Workflow.updated_at.desc())))


@app.post("/api/v1/workflows", response_model=WorkflowOut)
def create_workflow(payload: WorkflowCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    workflow = Workflow(tenant_id=user.tenant_id, **payload.model_dump())
    db.add(workflow); db.commit(); db.refresh(workflow)
    return workflow


@app.get("/api/v1/workflows/{workflow_id}", response_model=WorkflowOut)
def workflow_detail(workflow_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    workflow = db.scalar(select(Workflow).where(Workflow.id == workflow_id, Workflow.tenant_id == user.tenant_id))
    if not workflow: raise HTTPException(404, "Workflow not found")
    return workflow


@app.put("/api/v1/workflows/{workflow_id}", response_model=WorkflowOut)
def update_workflow(workflow_id: str, payload: WorkflowUpdate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    workflow = workflow_detail(workflow_id, db, user)
    for key, value in payload.model_dump(exclude_none=True).items(): setattr(workflow, key, value)
    db.commit(); db.refresh(workflow)
    return workflow


@app.post("/api/v1/workflows/{workflow_id}/validate")
def validate(workflow_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    workflow = workflow_detail(workflow_id, db, user)
    errors = validate_graph(workflow.graph)
    return {"valid": not errors, "errors": errors}


@app.post("/api/v1/workflows/{workflow_id}/publish", response_model=WorkflowOut)
def publish(workflow_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    workflow = workflow_detail(workflow_id, db, user)
    errors = validate_graph(workflow.graph)
    if errors: raise HTTPException(422, errors)
    version = (db.scalar(select(func.max(WorkflowVersion.version)).where(WorkflowVersion.workflow_id == workflow.id)) or 0) + 1
    db.add(WorkflowVersion(workflow_id=workflow.id, version=version, graph=workflow.graph))
    workflow.status = "published"; db.commit(); db.refresh(workflow)
    return workflow


@app.post("/api/v1/workflows/{workflow_id}/execute", response_model=ExecutionOut)
def execute(workflow_id: str, payload: ExecutionRequest, db: Session = Depends(get_db), user: User = Depends(current_user)):
    workflow = workflow_detail(workflow_id, db, user)
    execution = Execution(tenant_id=user.tenant_id, workflow_id=workflow.id, input_data=payload.input_data)
    db.add(execution); db.commit(); db.refresh(execution)
    if settings.execution_mode == "celery":
        execute_workflow_task.delay(execution.id)
        return execution
    return execute_graph(db, execution, workflow.graph)


@app.get("/api/v1/executions", response_model=list[ExecutionOut])
def executions(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return list(db.scalars(select(Execution).where(Execution.tenant_id == user.tenant_id).order_by(Execution.created_at.desc())))


@app.get("/api/v1/executions/{execution_id}", response_model=ExecutionOut)
def execution_detail(execution_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    execution = db.scalar(select(Execution).where(Execution.id == execution_id, Execution.tenant_id == user.tenant_id))
    if not execution: raise HTTPException(404, "Execution not found")
    return execution


@app.get("/api/v1/executions/{execution_id}/logs", response_model=list[ExecutionLogOut])
def execution_logs(execution_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return execution_detail(execution_id, db, user).logs


@app.get("/api/v1/executions/{execution_id}/events")
async def execution_events(execution_id: str, user: User = Depends(current_user)):
    async def stream():
        previous = None
        for _ in range(120):
            with SessionLocal() as db:
                execution = db.scalar(select(Execution).where(Execution.id == execution_id, Execution.tenant_id == user.tenant_id))
                if not execution:
                    yield "event: error\ndata: {\"message\":\"not found\"}\n\n"
                    return
                payload = {"id": execution.id, "status": execution.status, "duration_ms": execution.duration_ms, "token_used": execution.token_used}
                encoded = json.dumps(payload)
                if encoded != previous:
                    yield f"data: {encoded}\n\n"
                    previous = encoded
                if execution.status in {"success", "failed", "cancelled"}:
                    return
            await asyncio.sleep(0.5)
    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/api/v1/templates")
def templates(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return [{"id": item.id, "name": item.name, "description": item.description, "category": item.category, "use_count": item.use_count, "graph": item.graph} for item in db.scalars(select(Template))]


@app.get("/api/v1/analytics/overview")
def analytics(db: Session = Depends(get_db), user: User = Depends(current_user)):
    executions = list(db.scalars(select(Execution).where(Execution.tenant_id == user.tenant_id)))
    success = sum(item.status == "success" for item in executions)
    return {"active_workflows": db.scalar(select(func.count()).select_from(Workflow).where(Workflow.tenant_id == user.tenant_id)) or 0, "executions": len(executions), "success_rate": round(success / len(executions) * 100, 1) if executions else 100.0, "token_used": sum(item.token_used for item in executions), "cost": round(sum(item.cost for item in executions), 4)}
