"""Index lifecycle foundation. No model downloads or changes to live retrieval.

Embedding is injected: production adapters must declare an immutable revision
and reject overlong inputs. Unit-test vectors are not semantic retrieval.
"""
import hashlib
import json
import math
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import select, update, or_, and_
from sqlalchemy.exc import IntegrityError
from .models import ServicePolicy, PolicyIndex

CHUNKER = "character-offset-v1"


def split_text(text, size=400, overlap=40):
    """Exact source offsets; temporary character baseline, not token-aware BGE chunks."""
    if not 0 <= overlap < size:
        raise ValueError("Invalid chunk size/overlap")
    result = []
    for start in range(0, len(text), size-overlap):
        end = min(start+size, len(text))
        if text[start:end].strip():
            result.append({"start": start, "end": end, "text": text[start:end]})
        if end == len(text):
            break
    return result


def enqueue(db, tenant_id, policy_id, model_revision):
    if not model_revision or len(model_revision) > 200:
        raise ValueError("Immutable model revision required")
    policy = db.scalar(select(ServicePolicy).where(ServicePolicy.id == policy_id, ServicePolicy.tenant_id == tenant_id))
    if not policy:
        raise LookupError("Policy not found")
    chunks = split_text(policy.text)
    digest = hashlib.sha256(json.dumps([policy.text, policy.version, CHUNKER, model_revision], ensure_ascii=False).encode()).hexdigest()
    query = select(PolicyIndex).where(PolicyIndex.tenant_id == tenant_id, PolicyIndex.policy_id == policy_id, PolicyIndex.fingerprint == digest)
    existing = db.scalar(query)
    if existing:
        return existing
    try:
        with db.begin_nested():
            item = PolicyIndex(tenant_id=tenant_id, policy_id=policy_id, fingerprint=digest,
                               model_revision=model_revision, chunks=chunks)
            db.add(item); db.flush()
    except IntegrityError:
        item = db.scalar(query)
        if item is None:
            raise
    return item


def claim(db, tenant_id, index_id, now=None):
    now = now or datetime.utcnow()
    db.execute(update(PolicyIndex).where(PolicyIndex.id == index_id, PolicyIndex.tenant_id == tenant_id,
        PolicyIndex.status == "running", PolicyIndex.expires_at <= now, PolicyIndex.attempts >= 3).values(
        status="failed", error="LeaseAttemptsExhausted", token=None, expires_at=None).execution_options(synchronize_session=False))
    token = str(uuid4())
    eligible = or_(PolicyIndex.status == "pending", and_(PolicyIndex.status == "running", PolicyIndex.expires_at <= now))
    changed = db.execute(update(PolicyIndex).where(PolicyIndex.id == index_id, PolicyIndex.tenant_id == tenant_id,
        PolicyIndex.attempts < 3, eligible).values(status="running", token=token, expires_at=now+timedelta(seconds=120),
        attempts=PolicyIndex.attempts+1, error=None).execution_options(synchronize_session=False)).rowcount
    db.commit()
    return token if changed else None


def validate_vectors(vectors, count):
    if not isinstance(vectors, list) or len(vectors) != count or not vectors:
        raise ValueError("Embedding count mismatch")
    if any(not isinstance(v, list) for v in vectors):
        raise ValueError("Each embedding must be a list")
    dimension = len(vectors[0])
    if not 1 <= dimension <= 4096:
        raise ValueError("Invalid dimension")
    normalized = []
    for vector in vectors:
        if len(vector) != dimension or any(type(x) not in (int, float) or not math.isfinite(x) for x in vector):
            raise ValueError("Invalid vector")
        norm = math.sqrt(sum(x*x for x in vector))
        if not math.isfinite(norm) or norm == 0:
            raise ValueError("Invalid norm")
        normalized.append([x/norm for x in vector])
    return normalized


def finish(db, tenant_id, index_id, token, vectors=None, error=None, now=None):
    now = now or datetime.utcnow()
    owned = db.scalar(select(PolicyIndex).where(PolicyIndex.id == index_id, PolicyIndex.tenant_id == tenant_id))
    if not owned:
        return False
    values = {"status": "failed", "error": error, "vectors": []} if error else {
        "status": "ready", "error": None, "vectors": validate_vectors(vectors, len(owned.chunks))}
    changed = db.execute(update(PolicyIndex).where(PolicyIndex.id == index_id, PolicyIndex.tenant_id == tenant_id,
        PolicyIndex.status == "running", PolicyIndex.token == token, PolicyIndex.expires_at > now).values(
        **values, token=None, expires_at=None).execution_options(synchronize_session=False)).rowcount
    db.commit()
    return bool(changed)


def retry(db, tenant_id, index_id):
    """Explicit bounded retry; never resets attempt count."""
    changed = db.execute(update(PolicyIndex).where(PolicyIndex.id == index_id, PolicyIndex.tenant_id == tenant_id,
        PolicyIndex.status == "failed", PolicyIndex.attempts < 3).values(status="pending", error=None).execution_options(synchronize_session=False)).rowcount
    db.commit()
    return bool(changed)


def run(factory, tenant_id, index_id, embedder):
    with factory() as db:
        token = claim(db, tenant_id, index_id)
        if not token:
            return False
        item = db.get(PolicyIndex, index_id)
        try:
            vectors = embedder([c["text"] for c in item.chunks], item.model_revision)
            return finish(db, tenant_id, index_id, token, vectors=vectors)
        except Exception as exc:
            db.rollback()
            finish(db, tenant_id, index_id, token, error=type(exc).__name__[:100])
            return False
