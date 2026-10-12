"""Small labelled synthetic evaluation. Mock results measure contracts, not LLM quality."""
import argparse
import json
import time
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from .agent_runtime import SYSTEM_PROMPT, classify_rule, make_snapshot, run_agent
from .agent_schemas import AgentResult
from .agent_tools import RELEASE_NOTES
from .config import settings
from .database import Base
from .llm import _post_with_retry
from .models import AgentFeedback, AgentRun, Tenant

CASES_PATH = Path(__file__).resolve().parents[1] / "evaluation" / "feedback_cases.json"


def single_response(case: dict, mode: str) -> tuple[dict, int]:
    if mode == "mock":
        category, owner = classify_rule(case["text"])
        return {"category": category, "owner": owner, "summary": "Mock 单次响应；未查询资料，需要补充证据。", "evidence_ids": [], "next_action": "needs_information"}, 0
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is required for live evaluation")
    response, _ = _post_with_retry(f"{settings.openai_base_url.rstrip('/')}/chat/completions", {"model": settings.openai_model, "messages": [{"role": "system", "content": SYSTEM_PROMPT + " No tools are available. Without evidence choose needs_information."}, {"role": "user", "content": json.dumps({"text": case["text"], "version": case["version"]}, ensure_ascii=False)}], "temperature": 0.2, "max_tokens": 1000}, {"Authorization": f"Bearer {settings.openai_api_key}"}, min(settings.llm_timeout, 30), 2, 0.5, max_retry_delay=2)
    data = response.json()
    return AgentResult.model_validate_json(data["choices"][0]["message"]["content"]).model_dump(), int(data.get("usage", {}).get("total_tokens", 0))


def evaluate(mode: str = "mock") -> dict:
    if mode not in {"mock", "openai"}:
        raise ValueError("Unsupported evaluation mode")
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    reports = []
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        for strategy in ("rule", "single_llm", "agent"):
            rows = []
            for case in cases:
                start = time.perf_counter()
                trace, tokens, error, retrieved = [], 0, None, []
                try:
                    if strategy == "rule":
                        category, owner = classify_rule(case["text"])
                        result = {"category": category, "owner": owner, "evidence_ids": [], "next_action": "needs_information"}
                    elif strategy == "single_llm":
                        result, tokens = single_response(case, mode)
                    else:
                        with Session(engine) as db:
                            tenant = Tenant(name="Isolated evaluation")
                            db.add(tenant); db.flush()
                            feedback = AgentFeedback(tenant_id=tenant.id, text=case["text"], version=case["version"])
                            db.add(feedback); db.flush()
                            if case.get("prior_text"):
                                db.add(AgentFeedback(tenant_id=tenant.id, text=case["prior_text"], version=case["version"]))
                                db.flush()
                            run = AgentRun(tenant_id=tenant.id, feedback_id=feedback.id, snapshot=make_snapshot(case["text"], case["version"], mode))
                            db.add(run); db.commit()
                            run_agent(db, run)
                            result, trace, tokens, error = run.result, run.trace, run.token_used, run.error_message
                            retrieved = result.get("evidence", [])
                    refs = result.get("evidence_ids", [])
                    known = {n["id"] for n in RELEASE_NOTES if n["version"] == case["version"]}
                    known.update(n["id"] for n in retrieved if n["id"].startswith("feedback-"))
                    valid_evidence = bool(refs) and all(ref in known for ref in refs) and (case["evidence_id"] in refs if case["evidence_id"] else False)
                    tool_names = [t["name"] for t in trace if t["kind"] == "tool" and t["status"] == "success"]
                    tool_complete = {"search_release_notes", "find_similar_feedback"}.issubset(tool_names) and (case["action"] != "confirm_ticket" or "draft_feedback_ticket" in tool_names)
                    action_correct = result.get("next_action") == case["action"]
                    rows.append({"case_id": case["id"], "category_correct": result.get("category") == case["category"], "owner_correct": result.get("owner") == case["owner"], "safe_completion": not error and action_correct and (valid_evidence if case["action"] == "confirm_ticket" else not refs), "evidence_correct": valid_evidence if case["action"] == "confirm_ticket" else not refs, "tool_complete": tool_complete if strategy == "agent" else None, "duplicate_retrieved": any(t.get("name") == "find_similar_feedback" and t.get("output", {}).get("results") for t in trace) if case.get("prior_text") else None, "tokens": tokens, "duration_ms": int((time.perf_counter() - start) * 1000), "error": error})
                except Exception as exc:
                    rows.append({"case_id": case["id"], "category_correct": False, "owner_correct": False, "safe_completion": False, "evidence_correct": False, "tool_complete": False if strategy == "agent" else None, "tokens": tokens, "duration_ms": int((time.perf_counter() - start) * 1000), "error": str(exc)})
            rates = {key: round(sum(row[key] is True for row in rows) / len(rows) * 100, 1) for key in ("category_correct", "owner_correct", "safe_completion", "evidence_correct")}
            reports.append({"strategy": strategy, "metrics": rates, "total_tokens": sum(r["tokens"] for r in rows), "duration_ms": sum(r["duration_ms"] for r in rows), "cost": None, "cases": rows})
    finally:
        engine.dispose()
    return {"mode": mode, "dataset": "feedback_cases.json", "sample_count": len(cases), "synthetic": True, "limitations": "8 synthetic labelled cases, no statistical significance. Rule/single response have no retrieval; agent has tools. Mock single response reuses the rule classifier. Mock metrics verify mechanics, not real model quality. Tokens are zero in Mock; cost is unavailable. Evidence checks validate IDs, not semantic entailment. No external tickets are created.", "reports": reports}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["mock", "openai"], default="mock")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = json.dumps(evaluate(args.mode), ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(report, encoding="utf-8")
    else:
        print(report)
