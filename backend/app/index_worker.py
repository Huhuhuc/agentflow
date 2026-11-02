"""Explicit bounded indexing batch: python -m app.index_worker.

Requires optional sentence-transformers and a previously downloaded local model.
Does not download weights, invoke a chat model, or change live search.
"""
from pathlib import Path
from sqlalchemy import select, or_, and_
from datetime import datetime
from .config import settings
from .database import SessionLocal
from .models import PolicyIndex
from .policy_index import run


class LocalEmbedder:
    def __init__(self, path, revision):
        if not path or not revision or not Path(path).is_dir():
            raise ValueError('Local embedding directory and revision required')
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(path, device='cpu', local_files_only=True, trust_remote_code=False)
        self.revision = revision

    def __call__(self, texts, revision):
        if revision != self.revision:
            raise ValueError('Embedding revision mismatch')
        for text in texts:
            ids = self.model.tokenizer(text, truncation=False)['input_ids']
            if len(ids) > self.model.max_seq_length:
                raise ValueError('Chunk exceeds embedding token limit; re-chunk before retry')
        return self.model.encode(texts, batch_size=8, normalize_embeddings=True).tolist()


def batch(factory, embedder, limit=10):
    if not 1 <= limit <= 100:
        raise ValueError('Batch limit must be 1..100')
    with factory() as db:
        query = select(PolicyIndex.tenant_id, PolicyIndex.id).where(or_(
            PolicyIndex.status == 'pending', and_(PolicyIndex.status == 'running',
            PolicyIndex.expires_at <= datetime.utcnow())))
        # A worker for a new embedding version must not consume old jobs' retries.
        if getattr(embedder, 'revision', None):
            query = query.where(PolicyIndex.model_revision == embedder.revision)
        jobs = list(db.execute(query.order_by(PolicyIndex.id).limit(limit)))
    return [{'id': ident, 'ready': run(factory, tenant, ident, embedder)} for tenant, ident in jobs]


if __name__ == '__main__':
    import json
    embedder = LocalEmbedder(settings.embedding_model_path, settings.embedding_revision)
    print(json.dumps(batch(SessionLocal, embedder)))
