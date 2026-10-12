"""Durable dispatch retry records. Worker claims, not broker delivery, grant execution."""
from datetime import timedelta
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from .business_recovery import utcnow
from .models import AgentRun, BusinessDispatch


def enqueue(factory, run_id):
    with factory() as db:
        run = db.get(AgentRun, run_id)
        if not run or run.status != "pending": return False
        if not db.get(BusinessDispatch, run_id):
            try:
                with db.begin_nested():
                    db.add(BusinessDispatch(run_id=run_id)); db.flush()
            except IntegrityError:
                pass
        now = utcnow()
        claimed = db.execute(update(BusinessDispatch).where(BusinessDispatch.run_id == run_id, BusinessDispatch.next_attempt_at <= now).values(next_attempt_at=now + timedelta(seconds=30), attempts=BusinessDispatch.attempts + 1)).rowcount
        db.commit()
        if not claimed: return False
    try:
        from .worker import execute_business_task
        execute_business_task.apply_async(args=[run_id], queue="business")
    except Exception as exc:
        with factory() as db:
            db.execute(update(BusinessDispatch).where(BusinessDispatch.run_id == run_id).values(last_error=type(exc).__name__)); db.commit()
        return False
    with factory() as db:
        db.execute(update(BusinessDispatch).where(BusinessDispatch.run_id == run_id).values(last_error=None)); db.commit()
    return True
