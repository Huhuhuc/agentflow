from celery import Celery

from .config import settings
from .database import SessionLocal
from .engine import execute_graph
from .models import Execution, Workflow


celery_app = Celery("agentflow", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(task_track_started=True, task_serializer="json", result_serializer="json", accept_content=["json"])


@celery_app.task(name="agentflow.execute")
def execute_workflow_task(execution_id: str) -> str:
    with SessionLocal() as db:
        execution = db.get(Execution, execution_id)
        if not execution:
            return "missing"
        workflow = db.get(Workflow, execution.workflow_id)
        if not workflow:
            execution.status = "failed"
            execution.error_message = "Workflow not found"
            db.commit()
            return "failed"
        execute_graph(db, execution, workflow.graph)
        return execution.status

