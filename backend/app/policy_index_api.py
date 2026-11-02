"""Tenant-scoped index control. Index construction is separate from live retrieval."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from .auth import current_user
from .database import get_db
from .models import PolicyIndex, ServicePolicy, User
from .config import settings
from .service_api import staff
from .policy_index import enqueue, retry

router = APIRouter(prefix='/api/v1/service', tags=['Policy indexes'])


def owned_policy(db, user, policy_id):
    policy = db.scalar(select(ServicePolicy).where(ServicePolicy.id == policy_id, ServicePolicy.tenant_id == user.tenant_id))
    if policy is None:
        raise HTTPException(404, 'Policy not found')
    return policy


def out(item):
    return {'id': item.id, 'policy_id': item.policy_id, 'status': item.status,
            'model_revision': item.model_revision, 'attempts': item.attempts,
            'chunks': len(item.chunks), 'error': item.error}


@router.get('/policies/{policy_id}/indexes')
def listing(policy_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    owned_policy(db, user, policy_id)
    return [out(i) for i in db.scalars(select(PolicyIndex).where(
        PolicyIndex.tenant_id == user.tenant_id, PolicyIndex.policy_id == policy_id).order_by(PolicyIndex.id))]


@router.post('/policies/{policy_id}/indexes', status_code=202)
def create(policy_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    staff(user)
    owned_policy(db, user, policy_id)
    if not settings.embedding_model_path or not settings.embedding_revision:
        raise HTTPException(503, 'Configure a local embedding model and immutable revision first')
    item = enqueue(db, user.tenant_id, policy_id, settings.embedding_revision)
    db.commit(); db.refresh(item)
    return out(item)


@router.post('/indexes/{index_id}/retry', status_code=202)
def retry_index(index_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    staff(user)
    item = db.scalar(select(PolicyIndex).where(PolicyIndex.id == index_id, PolicyIndex.tenant_id == user.tenant_id))
    if item is None:
        raise HTTPException(404, 'Index not found')
    if not retry(db, user.tenant_id, index_id):
        raise HTTPException(409, 'Index is not failed or retry budget exhausted')
    db.refresh(item)
    return out(item)
