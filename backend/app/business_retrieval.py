"""Tenant-snapshot retrieval with explicit hybrid and lexical fallback modes."""
import time
from functools import lru_cache
from concurrent.futures import Future, TimeoutError
from threading import Lock, Thread
from sqlalchemy import select

from .config import settings
from .models import PolicyIndex
from .retrieval import lexical_rank, vector_rank, fuse

_embedding_lock = Lock()
_pending_embedding = None


def _lexical(query, items):
    return lexical_rank(query, items), None


@lru_cache(maxsize=2)
def _embedder(path, revision):
    if not path or not revision:
        raise ValueError("embedding configuration is missing")
    from .index_worker import LocalEmbedder
    return LocalEmbedder(path, revision)


def _query_embedding(embedder, query):
    global _pending_embedding
    with _embedding_lock:
        if _pending_embedding is not None and not _pending_embedding.done():
            raise TimeoutError("previous_query_embedding_still_running")
        future = Future()
        _pending_embedding = future

        def run_embedding():
            try:
                future.set_result(embedder.queries([query]))
            except BaseException as exc:
                future.set_exception(exc)

        Thread(target=run_embedding, name="policy-query-embedding", daemon=True).start()

    def clear(completed):
        global _pending_embedding
        with _embedding_lock:
            if _pending_embedding is completed:
                _pending_embedding = None

    future.add_done_callback(clear)
    return future.result(timeout=settings.retrieval_embedding_timeout_seconds)[0]


def _mapped_indexes(snapshot, policy_ids):
    retrieval = snapshot.get("retrieval", {})
    indexes = {item["policy_id"]: item for item in snapshot.get("retrieval_indexes", [])}
    selected = [indexes.get(policy_id) for policy_id in policy_ids]
    if len(selected) != len(policy_ids) or any(item is None for item in selected):
        return None, "index_missing"
    if any(item.get("coverage", 0) < settings.retrieval_min_index_coverage for item in selected):
        return None, "index_coverage_insufficient"
    if any(item.get("model_revision") != settings.embedding_revision for item in selected):
        return None, "embedding_revision_mismatch"
    return selected, None


def search_policy(query, items, snapshot, db, tenant_id):
    """Return ranked snapshot evidence and an auditable retrieval status."""
    start = time.perf_counter()
    lexical, _ = _lexical(query, items)
    result = {
        "retrieval": "lexical",
        "fallback_reason": None,
        "abstained": False,
        "duration_ms": 0,
    }
    if snapshot.get("retrieval", {}).get("requested_mode", settings.retrieval_mode) != "hybrid":
        result["duration_ms"] = int((time.perf_counter() - start) * 1000)
        return lexical[:5], result

    policy_ids = list(dict.fromkeys(item.get("policy_id") for item in items if item.get("policy_id")))
    if not items or not policy_ids:
        result["duration_ms"] = int((time.perf_counter() - start) * 1000)
        return [], result
    selected, reason = _mapped_indexes(snapshot, policy_ids)
    if reason:
        result.update(retrieval="lexical_fallback", fallback_reason=reason)
        result["duration_ms"] = int((time.perf_counter() - start) * 1000)
        return lexical[:5], result

    try:
        if db is None or not tenant_id:
            raise ValueError("index_session_missing")
        embedder = _embedder(settings.embedding_model_path, settings.embedding_revision)
        query_vector = _query_embedding(embedder, query)
        index_ids = [item["index_id"] for item in selected]
        persisted = list(db.scalars(select(PolicyIndex).where(
            PolicyIndex.tenant_id == tenant_id,
            PolicyIndex.id.in_(index_ids),
            PolicyIndex.status == "ready",
            PolicyIndex.model_revision == settings.embedding_revision,
        )))
        by_id = {item.id: item for item in persisted}
        if len(by_id) != len(index_ids):
            raise ValueError("index_snapshot_unavailable")
        vector_rows = []
        index_revisions = []
        for index in selected:
            record = by_id[index["index_id"]]
            index_revisions.append(index["model_revision"])
            for mapping in index["mapped_chunks"]:
                chunk_index = mapping["chunk_index"]
                if chunk_index >= len(record.vectors) or chunk_index >= len(record.chunks):
                    raise ValueError("index_mapping_invalid")
                vector_rows.append((mapping["evidence_id"], record.vectors[chunk_index], index["policy_id"]))
        if not vector_rows:
            raise ValueError("index_has_no_mapped_chunks")
        vectors = [row[1] for row in vector_rows]
        dense = vector_rank(query_vector, vectors, [{"id": row[0]} for row in vector_rows])
        best_by_evidence = {}
        for position in dense:
            evidence_id = vector_rows[position][0]
            score = sum(a * b for a, b in zip(query_vector, vector_rows[position][1]))
            best_by_evidence[evidence_id] = max(best_by_evidence.get(evidence_id, float("-inf")), score)
        evidence_ids = [item["id"] for item in items]
        dense_evidence = sorted(
            (evidence_id for evidence_id in evidence_ids if evidence_id in best_by_evidence),
            key=lambda evidence_id: (-best_by_evidence[evidence_id], evidence_id),
        )
        lexical_ids = [evidence_ids[index] for index in lexical[:20]]
        fused_ids = fuse(
            [evidence_ids.index(evidence_id) for evidence_id in lexical_ids],
            [evidence_ids.index(evidence_id) for evidence_id in dense_evidence],
        )
        ranked = fused_ids[:5]
        top_evidence_id = evidence_ids[ranked[0]] if ranked else None
        top_score = best_by_evidence.get(top_evidence_id) if top_evidence_id else None
        result.update(retrieval="hybrid", index_revision=sorted(set(index_revisions)))
        threshold = snapshot.get("retrieval", {}).get("threshold")
        if threshold is not None and (top_score is None or top_score < threshold):
            result["abstained"] = True
            ranked = []
        result["duration_ms"] = int((time.perf_counter() - start) * 1000)
        return ranked, result
    except Exception as exc:
        result.update(retrieval="lexical_fallback", fallback_reason=type(exc).__name__)
        result["duration_ms"] = int((time.perf_counter() - start) * 1000)
        return lexical[:5], result
