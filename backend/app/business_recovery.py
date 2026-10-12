"""Database-fenced execution. Tools are read-only or draft-only; confirmations are separate."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import exists, select, update, or_, and_

from .models import AgentRun, BusinessLease
from .config import settings

LEASE_SECONDS = 150  # Longer than the 120-second bounded execution attempt.
MAX_ATTEMPTS = 3
log = logging.getLogger(__name__)


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def claim(db, run_id, allow_failed=False):
    allowed = ["pending", "failed"] if allow_failed else ["pending"]
    # Acquire the run row first in every transaction; never hold it across network I/O.
    changed = db.execute(update(AgentRun).where(AgentRun.id == run_id, AgentRun.status.in_(allowed)).values(status="running", error_message=None).execution_options(synchronize_session=False)).rowcount
    if not changed:
        db.rollback()
        return None
    lease = db.get(BusinessLease, run_id)
    if lease and lease.attempts >= MAX_ATTEMPTS:
        db.execute(update(AgentRun).where(AgentRun.id == run_id).values(status="failed", error_message="Maximum execution attempts reached; create a new run"))
        db.commit()
        return None
    token = str(uuid4())
    expires = utcnow() + timedelta(seconds=LEASE_SECONDS)
    if lease:
        lease.token, lease.expires_at, lease.attempts = token, expires, lease.attempts + 1
    else:
        db.add(BusinessLease(run_id=run_id, token=token, expires_at=expires))
    db.commit()
    return token


def persist(db, run_id, token, **values):
    """One conditional statement fences cancelled tasks and late/stale workers."""
    owns = exists().where(BusinessLease.run_id == run_id, BusinessLease.token == token, BusinessLease.expires_at > utcnow())
    changed = db.execute(update(AgentRun).where(AgentRun.id == run_id, AgentRun.status == "running", owns).values(**values).execution_options(synchronize_session=False)).rowcount
    db.commit()
    return bool(changed)


def recover(db, now=None):
    now = now or utcnow()
    expired = or_(exists().where(BusinessLease.run_id == AgentRun.id, BusinessLease.expires_at <= now),
                  and_(~exists().where(BusinessLease.run_id == AgentRun.id), AgentRun.created_at <= now - timedelta(seconds=LEASE_SECONDS)))
    ids = list(db.scalars(select(AgentRun.id).where(AgentRun.status == "running", AgentRun.snapshot["runtime_version"].as_string() == "business-agent-v1", expired)))
    recovered = []
    for rid in ids:
        changed = db.execute(update(AgentRun).where(AgentRun.id == rid, AgentRun.status == "running", expired).values(status="pending", error_message="Worker lease expired; resuming last committed checkpoint").execution_options(synchronize_session=False)).rowcount
        if changed:
            # The next claim issues a different token. No old worker can save in pending.
            recovered.append(rid)
    db.commit()
    return recovered


def sweep(factory):
    from .service_experiments import expire_experiments
    expire_experiments(factory)
    with factory() as db:
        recover(db)
        query = select(AgentRun.id).where(AgentRun.status == "pending", AgentRun.snapshot["runtime_version"].as_string() == "business-agent-v1")
        if settings.execution_mode == "celery":
            from .models import BusinessDispatch
            query = query.where(or_(~exists().where(BusinessDispatch.run_id == AgentRun.id),
                                   exists().where(BusinessDispatch.run_id == AgentRun.id, BusinessDispatch.next_attempt_at <= utcnow())))
        return list(db.scalars(query.order_by(AgentRun.created_at).limit(2)))


def execute_pending(factory, rid):
    from .business_agent import run_business
    with factory() as db:
        token = claim(db, rid)
        if token:
            run_business(db, db.get(AgentRun, rid), lease_token=token)


async def watchdog(factory, stop):
    active = set()
    try:
        while not stop.is_set():
            # Expiry scanning never waits for a provider response. At most two fallback
            # workers run per server; DB claim also fences multiple server processes.
            try:
                ids = await asyncio.to_thread(sweep, factory)
                done = {t for t in active if t.done()}
                for task in done:
                    try: task.result()
                    except Exception: log.exception("Recovered business execution failed")
                active -= done
                for rid in ids[:max(0, 2 - len(active))]:
                    if settings.execution_mode == "celery":
                        from .business_queue import enqueue
                        active.add(asyncio.create_task(asyncio.to_thread(enqueue, factory, rid)))
                    else:
                        active.add(asyncio.create_task(asyncio.to_thread(execute_pending, factory, rid)))
            except Exception:
                log.exception("Business recovery sweep failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass
    finally:
        await asyncio.gather(*active, return_exceptions=True)
