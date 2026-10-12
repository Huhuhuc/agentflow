"""Tenant-scoped lexical retrieval and side-effect-free ticket drafting."""
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .agent_schemas import DraftTicket, SearchFeedback, SearchNotes
from .models import AgentFeedback

KNOWLEDGE_VERSION = "demo-release-notes-v1"
RELEASE_NOTES = [
    {"id": "note-2.4-damage", "version": "2.4", "title": "技能伤害更新", "text": "2.4 示例版本将火球技能伤害倍率由 1.0 调整为 1.1。伤害异常需要提供角色、装备与复现步骤。", "source": "demo://release-notes/2.4/damage"},
    {"id": "note-2.4-crash", "version": "2.4", "title": "闪退排查说明", "text": "2.4 示例版本正在收集闪退和崩溃报告。需要设备型号、日志与复现步骤；该记录不代表已确认根因或已修复。", "source": "demo://release-notes/2.4/crash"},
    {"id": "note-2.4-match", "version": "2.4", "title": "匹配体验说明", "text": "2.4 示例版本匹配队列按段位与区域划分。等待时间和匹配体验问题需要区域、时间与段位信息。", "source": "demo://release-notes/2.4/match"},
]


def terms(text: str) -> set[str]:
    words = set(re.findall(r"[a-z][a-z0-9]+", text.lower()))
    chinese = re.findall(r"[\u4e00-\u9fff]+", text)
    for word in chinese:
        words.update(word[i:i + 2] for i in range(len(word) - 1))
    return words - {"版本", "更新", "示例", "需要", "提供", "请核", "核实", "复现", "步骤", "信息", "报告", "问题", "处理", "后请", "新后"}


def overlap(query: str, document: str) -> int:
    return len(terms(query) & terms(document))


ARGUMENTS = {
    "search_release_notes": SearchNotes,
    "find_similar_feedback": SearchFeedback,
    "draft_feedback_ticket": DraftTicket,
}
DESCRIPTIONS = {
    "search_release_notes": "Search demo release notes by query and exact version. Returns source IDs and excerpts. Empty results mean missing evidence.",
    "find_similar_feedback": "Find similar reports in the current tenant. Results are unverified user reports, not confirmed facts.",
    "draft_feedback_ticket": "Prepare a ticket draft using retrieved evidence IDs. Does NOT create or send a ticket. Human confirmation is required.",
}


def tool_definitions() -> list[dict]:
    return [{"type": "function", "function": {"name": name, "description": DESCRIPTIONS[name], "parameters": schema.model_json_schema()}} for name, schema in ARGUMENTS.items()]


def invoke_tool(name: str, arguments: dict, db: Session, tenant_id: str, feedback_id: str, version: str, evidence: dict[str, dict], notes: list[dict] | None = None) -> dict[str, Any]:
    if name not in ARGUMENTS:
        raise ValueError(f"Unknown tool: {name}")
    payload = ARGUMENTS[name].model_validate(arguments)
    if name == "search_release_notes":
        if payload.version != version:
            raise ValueError("Release-note version must match the submitted feedback")
        ranked = sorted((notes if notes is not None else RELEASE_NOTES), key=lambda n: overlap(payload.query, n["title"] + n["text"]), reverse=True)
        candidates = [(n, overlap(payload.query, n["title"] + n["text"])) for n in ranked if n["version"] == version]
        best = max((score for _, score in candidates), default=0)
        results = [dict(n) for n, score in candidates if score > 0 and score >= best * 0.6][:3]
    elif name == "find_similar_feedback":
        reports = db.scalars(select(AgentFeedback).where(AgentFeedback.tenant_id == tenant_id, AgentFeedback.id != feedback_id, AgentFeedback.version == version).order_by(AgentFeedback.created_at.desc()).limit(200))
        results = [{"id": f"feedback-{r.id}", "text": r.text, "source": f"feedback://{r.id}", "verified": False} for r in reports if overlap(payload.query, r.text) >= 2][:3]
    else:
        if any(ref not in evidence for ref in payload.evidence_ids):
            raise ValueError("Draft references evidence not retrieved in this run")
        if not any(ref.startswith("note-") for ref in payload.evidence_ids):
            raise ValueError("A draft requires release-note evidence; similar reports alone are insufficient")
        return {"draft": payload.model_dump(), "requires_confirmation": True, "persisted": False}
    for result in results:
        evidence[result["id"]] = result
    return {"results": results, "retrieval": "lexical", "demo_data": name == "search_release_notes"}
