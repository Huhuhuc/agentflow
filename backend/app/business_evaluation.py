"""Repeatable business-agent evaluation, isolated from operational data and ticket writes."""
import argparse
import csv
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from .business_agent import run_business, snapshot
from .config import settings
from .database import Base
from .models import AgentFeedback, AgentRun, Tenant

CASES = Path(__file__).resolve().parents[1] / "evaluation/business_cases.json"


def score(case, run):
    result = run.result
    refs = set(result.get("evidence_ids", []))
    expected = {x for x in ("order-" + case["order"] if case["order"] else None, case["policy"]) if x}
    retrieved = {e["id"] for e in result.get("evidence", [])}
    tools = [t for t in run.trace if t.get("kind") == "tool"]
    names = {t["name"] for t in tools if t["status"] == "success"}
    correct_order = any(t["name"] == "get_order" and t.get("output", {}).get("order", {}).get("id") == case["order"] for t in tools)
    tool_ok = (({"get_order", "search_policy"} <= names and correct_order) if expected else True)
    tool_ok = tool_ok and (("draft_ticket" in names) == (case["action"] == "confirm_ticket"))
    checks = {
        "execution_ok": run.status in {"completed", "awaiting_confirmation", "needs_information"},
        "action_correct": result.get("next_action") == case["action"],
        "tool_contract_correct": bool(tool_ok),
        "citation_correct": expected <= refs and refs <= retrieved and (not expected or refs == expected),
        "draft_order_correct": not result.get("draft") or result["draft"].get("order_id") == case["order"],
    }
    return {**checks, "contract_pass": all(checks.values())}


def evaluate(mode="mock", split="dev", repeats=1, limit=None, input_price=None, output_price=None, adapter=None, cases_override=None, on_progress=None, model=None):
    if mode not in {"mock", "openai"} or split not in {"dev", "test"}: raise ValueError("Unsupported mode/split")
    if mode == "openai" and not settings.openai_api_key and adapter is None: raise ValueError("OPENAI_API_KEY is missing; real results were not generated")
    if not 1 <= repeats <= 5: raise ValueError("repeats must be 1..5")
    if limit is not None and not 1 <= limit <= 12: raise ValueError("limit must be 1..12")
    if (input_price is None) != (output_price is None): raise ValueError("Set both input and output prices per million tokens")
    if any(p is not None and (not math.isfinite(p) or p < 0) for p in (input_price, output_price)): raise ValueError("Prices must be finite and non-negative")
    raw = json.dumps(cases_override, ensure_ascii=False, sort_keys=True).encode() if cases_override is not None else CASES.read_bytes()
    cases = [c for c in json.loads(raw) if c["split"] == split][:limit]
    if not cases: raise ValueError("Selected split contains no cases")
    rows = []
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            tenant = Tenant(name="Isolated evaluation"); db.add(tenant); db.commit()
            for repeat in range(1, repeats + 1):
                for case in cases:
                    feedback = AgentFeedback(tenant_id=tenant.id, text=case["text"], version="business-eval-v1")
                    db.add(feedback); db.flush()
                    snap = snapshot(case["text"], mode)  # Gold labels never reach the model.
                    if model and mode == "openai": snap["model"] = model
                    run = AgentRun(tenant_id=tenant.id, feedback_id=feedback.id, snapshot=snap)
                    db.add(run); db.commit()
                    run_business(db, run, adapter=adapter)
                    turns = [t for t in run.trace if t.get("kind") == "model"]
                    usages = [t.get("usage") for t in turns]
                    complete = bool(usages) and all(isinstance(u, dict) and all(isinstance(u.get(k), int) and u[k] >= 0 for k in ("prompt_tokens", "completion_tokens")) for u in usages)
                    # Retries, failed parsing and crashes can incur unreported provider charges.
                    complete = complete and run.status != "failed" and all(t.get("attempts", 1) <= 1 for t in turns)
                    prompt = sum(u["prompt_tokens"] for u in usages) if complete else None
                    completion = sum(u["completion_tokens"] for u in usages) if complete else None
                    cost = ((prompt * input_price + completion * output_price) / 1_000_000) if complete and input_price is not None and mode == "openai" else None
                    rows.append({"id": case["id"], "repeat": repeat, "category": case["category"], "text": case["text"], "expected_action": case["action"],
                                 **score(case, run), "actual_action": run.result.get("next_action"), "status": run.status,
                                 "latency_ms": run.duration_ms, "observed_total_tokens": run.token_used if mode == "openai" and (complete or any(isinstance(u, dict) and isinstance(u.get("total_tokens"), int) for u in usages)) else None,
                                 "usage_complete": complete if mode == "openai" else False, "prompt_tokens": prompt, "completion_tokens": completion,
                                 "estimated_cost": cost, "error": run.error_message, "result": run.result, "trace": run.trace,
                                 "human_review": {"status": "pending", "rubric": case["fact"], "factual_correct": None, "notes": ""}})
                    if on_progress: on_progress({"completed": len(rows), "total": len(cases) * repeats, "last_case": case["id"]})
    finally:
        engine.dispose()
    latencies = sorted(r["latency_ms"] for r in rows)
    metrics = {k + "_rate": sum(r[k] for r in rows) / len(rows) for k in ("execution_ok", "action_correct", "tool_contract_correct", "citation_correct", "contract_pass")}
    metrics.update({"cases": len(rows), "p50_ms": latencies[math.ceil(len(rows)*.5)-1], "p95_ms": latencies[math.ceil(len(rows)*.95)-1],
                    "estimated_cost": sum(r["estimated_cost"] for r in rows) if all(r["estimated_cost"] is not None for r in rows) else None,
                    "total_tokens": sum(r["observed_total_tokens"] for r in rows) if all(r["usage_complete"] for r in rows) else None,
                    "usage_complete_cases": sum(r["usage_complete"] for r in rows),
                    "semantic_success_rate": None, "human_review_pending": len(rows)})
    return {"schema": "business-eval-v1", "created_at": datetime.now(timezone.utc).isoformat(), "mode": mode,
            "model": (model or settings.openai_model) if mode == "openai" else "deterministic-demo", "split": split, "repeats": repeats,
            "dataset_sha256": hashlib.sha256(raw).hexdigest(), "runtime_sha256": hashlib.sha256(Path(__file__).with_name("business_agent.py").read_bytes()).hexdigest(),
            "input_price_per_million": input_price, "output_price_per_million": output_price,
            "notice": "Mock measures contracts, not model quality. Automatic checks do not establish factual correctness. Human review is required. Cost is an estimate in the supplied price currency; missing usage is unknown, not zero.",
            "metrics": metrics, "rows": rows}


def compare_reports(current, previous):
    if previous.get("schema") != "business-eval-v1" or any(current[k] != previous.get(k) for k in ("dataset_sha256", "split", "repeats")):
        raise ValueError("Comparison requires the same dataset hash, split and repeats")
    if [(r["id"], r["repeat"]) for r in current["rows"]] != [(r["id"], r["repeat"]) for r in previous["rows"]]:
        raise ValueError("Comparison requires the same selected cases")
    deltas = {k: value - previous["metrics"][k] for k, value in current["metrics"].items() if isinstance(value, (int, float)) and isinstance(previous["metrics"].get(k), (int, float))}
    return {"baseline_model": previous["model"], "baseline_mode": previous["mode"], "baseline_runtime_sha256": previous["runtime_sha256"], "metric_deltas": deltas,
            "new_failures": [row["id"] for row, old in zip(current["rows"], previous["rows"]) if old["contract_pass"] and not row["contract_pass"]]}


def export_report(report, path):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    columns = ["id", "repeat", "category", "contract_pass", "actual_action", "action_correct", "tool_contract_correct", "citation_correct", "latency_ms", "observed_total_tokens", "usage_complete", "estimated_cost", "error"]
    with path.with_suffix(".csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore"); writer.writeheader(); writer.writerows(report["rows"])
    failures = [r for r in report["rows"] if not r["contract_pass"]]
    lines = ["# 企业服务 Agent 评测", f"模式：{report['mode']}；模型：{report['model']}；分组：{report['split']}",
             "\n自动检查仅衡量契约；事实正确性仍需人工复核。Mock 不代表真实模型能力。", "\n```json", json.dumps(report["metrics"], ensure_ascii=False, indent=2), "```", "\n## 失败样本"]
    lines += [f"- {r['id']} / 第{r['repeat']}轮：{r['text']}；预期 {r['expected_action']}，实际 {r['actual_action']}；错误：{r['error'] or '自动契约检查未通过'}" for r in failures]
    path.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["mock", "openai"], default="mock")
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--input-price", type=float)
    parser.add_argument("--output-price", type=float)
    parser.add_argument("--output", default="evaluation/reports/business-latest.json")
    parser.add_argument("--compare", help="Compare with a previous JSON report using identical cases")
    args = parser.parse_args()
    try:
        # Validate baseline shape before any paid model calls.
        previous = json.loads(Path(args.compare).read_text(encoding="utf-8")) if args.compare else None
        if previous:
            expected = [c for c in json.loads(CASES.read_bytes()) if c["split"] == args.split][:args.limit]
            signature = [(c["id"], n) for n in range(1, args.repeats + 1) for c in expected]
            if previous.get("schema") != "business-eval-v1" or previous.get("dataset_sha256") != hashlib.sha256(CASES.read_bytes()).hexdigest() or previous.get("split") != args.split or previous.get("repeats") != args.repeats or [(r["id"], r["repeat"]) for r in previous.get("rows", [])] != signature:
                raise ValueError("Baseline dataset, split, repeats and selected cases must match")
        report = evaluate(args.mode, args.split, args.repeats, args.limit, args.input_price, args.output_price)
        if previous: report["comparison"] = compare_reports(report, previous)
    except ValueError as exc:
        parser.error(str(exc))
    export_report(report, args.output)
    print(json.dumps(report["metrics"], ensure_ascii=False))
    print(f"Report: {Path(args.output).resolve()}")


if __name__ == "__main__":
    main()
