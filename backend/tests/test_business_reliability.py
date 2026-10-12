from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier, Event

import pytest
from sqlalchemy import create_engine, select, update, func
from sqlalchemy.orm import sessionmaker

from app.business_agent import run_business, snapshot, mock_turn
from app.business_api import accept
from app.business_recovery import claim, persist, recover, MAX_ATTEMPTS
from app.database import Base
from app.models import AgentRun, AgentFeedback, AgentTicket, BusinessLease, Tenant, User


@pytest.fixture
def disk(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "concurrent.db"), connect_args={"check_same_thread": False, "timeout": 10})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        t = Tenant(name="Concurrent"); db.add(t); db.flush()
        f = AgentFeedback(tenant_id=t.id, text="A102退款请生成工单")
        u = User(tenant_id=t.id, email="concurrent@example.test", name="tester", password_hash="unused")
        db.add_all([f, u]); db.flush()
        r = AgentRun(tenant_id=t.id, feedback_id=f.id, snapshot=snapshot(f.text, "mock"))
        db.add(r); db.commit()
        ids = r.id, u.id
    yield factory, *ids
    engine.dispose()


def test_only_one_concurrent_worker_claims(disk):
    factory, rid, _ = disk
    barrier = Barrier(2)
    def work():
        with factory() as db:
            barrier.wait(timeout=5)
            return claim(db, rid)
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(work) for _ in range(2)]
        assert sum(bool(f.result(timeout=10)) for f in futures) == 1


def test_cancel_inflight_response_cannot_overwrite(disk):
    factory, rid, _ = disk
    entered, release = Event(), Event()
    def delayed(messages, snap):
        entered.set(); assert release.wait(5)
        return mock_turn(messages, snap)
    def worker():
        with factory() as db: run_business(db, db.get(AgentRun, rid), delayed)
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(worker)
        assert entered.wait(5)
        try:
            with factory() as db:
                db.execute(update(AgentRun).where(AgentRun.id == rid).values(status="cancelled")); db.commit()
        finally:
            release.set()
        future.result(timeout=10)
    with factory() as db:
        run = db.get(AgentRun, rid)
        assert run.status == "cancelled" and not run.result
        assert not db.scalar(select(AgentTicket))


def test_crash_checkpoint_recovery_and_stale_worker_fencing(disk):
    factory, rid, _ = disk
    class ProcessCrash(BaseException): pass
    calls = 0
    def crash(messages, snap):
        nonlocal calls
        calls += 1
        if calls == 2: raise ProcessCrash()
        return mock_turn(messages, snap)
    with factory() as db:
        with pytest.raises(ProcessCrash): run_business(db, db.get(AgentRun, rid), crash)
        lease = db.get(BusinessLease, rid)
        old_token = lease.token
        assert db.get(AgentRun, rid).result["checkpoint"]["step"] == 1
        lease.expires_at = datetime.utcnow() - timedelta(seconds=1); db.commit()
        assert recover(db) == [rid]
        new_token = claim(db, rid)
        assert new_token and new_token != old_token
        assert not persist(db, rid, old_token, status="completed", result={"stale": True})
        run = run_business(db, db.get(AgentRun, rid), lease_token=new_token)
        assert run.status == "awaiting_confirmation"
        assert sum(t.get("name") == "get_order" for t in run.trace) == 1


def test_recovery_attempts_are_bounded(disk):
    factory, rid, _ = disk
    with factory() as db:
        for _ in range(MAX_ATTEMPTS):
            assert claim(db, rid)
            db.get(BusinessLease, rid).expires_at = datetime.utcnow() - timedelta(seconds=1); db.commit()
            recover(db)
        assert claim(db, rid) is None
        db.expire_all()
        assert db.get(AgentRun, rid).status == "failed"


def test_two_confirmations_create_one_ticket(disk):
    factory, rid, uid = disk
    with factory() as db: run_business(db, db.get(AgentRun, rid))
    barrier = Barrier(2)
    def confirm():
        with factory() as db:
            user = db.get(User, uid)
            barrier.wait(timeout=5)
            return accept(rid, db, user)["id"]
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(confirm) for _ in range(2)]
        assert len({f.result(timeout=10) for f in futures}) == 1
    with factory() as db: assert db.scalar(select(func.count()).select_from(AgentTicket)) == 1


def test_hard_process_exit_recovers_committed_checkpoint(disk):
    import subprocess
    import sys
    from app.business_recovery import sweep, execute_pending
    factory, rid, _ = disk
    script = """
import os, sys
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.business_agent import run_business, mock_turn
from app.models import AgentRun
engine = create_engine(sys.argv[1])
def crash(messages, snap):
    if any(m['role'] == 'tool' for m in messages): os._exit(77)
    return mock_turn(messages, snap)
with Session(engine) as db:
    run_business(db, db.get(AgentRun, sys.argv[2]), crash)
"""
    child = subprocess.run([sys.executable, "-c", script, str(factory.kw["bind"].url), rid], timeout=15, capture_output=True)
    assert child.returncode == 77, child.stderr.decode(errors="replace")
    with factory() as db:
        run = db.get(AgentRun, rid)
        assert run.status == "running" and run.result["checkpoint"]["step"] == 1
        db.get(BusinessLease, rid).expires_at = datetime.utcnow() - timedelta(seconds=1); db.commit()
    assert rid in sweep(factory)
    execute_pending(factory, rid)
    with factory() as db:
        run = db.get(AgentRun, rid)
        assert run.status == "awaiting_confirmation"
        assert sum(t.get("name") == "get_order" for t in run.trace) == 1


def test_legacy_stuck_running_is_recovered_without_touching_other_agents(disk):
    factory, rid, _ = disk
    with factory() as db:
        run = db.get(AgentRun, rid)
        run.status = "running"
        run.created_at = datetime.utcnow() - timedelta(minutes=5)
        other = AgentRun(tenant_id=run.tenant_id, feedback_id=run.feedback_id, status="running", snapshot={"runtime_version": "feedback-agent-v1"}, created_at=run.created_at)
        db.add(other); db.commit()
        assert recover(db) == [rid]
        db.expire_all()
        assert db.get(AgentRun, other.id).status == "running"
