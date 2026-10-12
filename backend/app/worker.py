from celery import Celery

from .config import settings
from .database import SessionLocal
from .engine import execute_graph
from .models import Execution, Workflow, WorkflowRunSnapshot


celery_app = Celery("agentflow", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(task_track_started=True, task_serializer="json", result_serializer="json", accept_content=["json"])
celery_app.conf.update(broker_connection_timeout=3, task_publish_retry=False, worker_prefetch_multiplier=1)


@celery_app.task(name="agentflow.business", acks_late=True, reject_on_worker_lost=True)
def execute_business_task(run_id: str):
    from .business_recovery import execute_pending
    execute_pending(SessionLocal, run_id)
    return run_id


@celery_app.task(name="agentflow.experiment", acks_late=True, reject_on_worker_lost=True)
def execute_experiment_task(experiment_id: str):
    from .service_experiments import execute_experiment
    execute_experiment(SessionLocal, experiment_id)
    return experiment_id


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
        snapshot = db.get(WorkflowRunSnapshot, execution.id)
        execute_graph(db, execution, snapshot.graph if snapshot else workflow.graph)
        return execution.status

