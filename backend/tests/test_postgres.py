"""CI exercises PostgreSQL claims; local runs skip without TEST_POSTGRES_URL."""
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.migrations import upgrade
from app.models import Tenant,AgentFeedback,AgentRun
from app.business_agent import snapshot
from app.business_recovery import claim


@pytest.mark.skipif(not os.getenv("TEST_POSTGRES_URL"),reason="PostgreSQL test service not configured")
def test_postgres_migration_and_concurrent_claim():
    engine=create_engine(os.environ["TEST_POSTGRES_URL"])
    upgrade(engine)
    factory=sessionmaker(bind=engine,expire_on_commit=False)
    with factory() as db:
        tenant=Tenant(name="Postgres concurrency");db.add(tenant);db.flush()
        feedback=AgentFeedback(tenant_id=tenant.id,text="A101退款");db.add(feedback);db.flush()
        run=AgentRun(tenant_id=tenant.id,feedback_id=feedback.id,snapshot=snapshot(feedback.text,"mock"));db.add(run);db.commit();rid=run.id
    barrier=Barrier(2)
    def work():
        with factory() as db:barrier.wait(timeout=5);return claim(db,rid)
    with ThreadPoolExecutor(2) as pool:
        futures=[pool.submit(work) for _ in range(2)]
        assert sum(bool(f.result(timeout=10)) for f in futures)==1
    engine.dispose()
