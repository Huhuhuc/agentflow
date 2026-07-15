from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import hash_password
from .models import Template, Tenant, User, Workflow


DEMO_GRAPH = {
    "nodes": [
        {"id": "trigger", "type": "trigger", "position": {"x": 40, "y": 170}, "data": {"label": "工单创建", "config": {}}},
        {"id": "classify", "type": "agent", "position": {"x": 280, "y": 170}, "data": {"label": "意图分类", "config": {"model": "Mock Agent"}}},
        {"id": "route", "type": "condition", "position": {"x": 520, "y": 170}, "data": {"label": "置信度路由", "config": {"field": "classify.category", "value": "inquiry"}}},
        {"id": "answer", "type": "agent", "position": {"x": 760, "y": 80}, "data": {"label": "知识库回复", "config": {"model": "Mock RAG"}}},
        {"id": "review", "type": "notification", "position": {"x": 760, "y": 270}, "data": {"label": "转人工", "config": {"channel": "manual-review", "message": "低置信度工单需要人工处理"}}},
        {"id": "output", "type": "output", "position": {"x": 1000, "y": 170}, "data": {"label": "输出结果", "config": {"template": "{{classify}}"}}},
    ],
    "edges": [
        {"id": "e1", "source": "trigger", "target": "classify"},
        {"id": "e2", "source": "classify", "target": "route"},
        {"id": "e3", "source": "route", "target": "answer", "label": "true"},
        {"id": "e4", "source": "route", "target": "review", "label": "false"},
        {"id": "e5", "source": "answer", "target": "output"},
        {"id": "e6", "source": "review", "target": "output"},
    ],
}


def seed(db: Session) -> None:
    if db.scalar(select(User).where(User.email == "demo@agentflow.dev")):
        return
    tenant = Tenant(name="AgentFlow Demo Team", plan="pro")
    db.add(tenant)
    db.flush()
    db.add(User(tenant_id=tenant.id, email="demo@agentflow.dev", password_hash=hash_password("demo1234"), name="胡宸凡", role="admin"))
    db.add(Workflow(tenant_id=tenant.id, name="智能客服工单处理", description="工单分类 → AI 回复 / 转人工", status="published", graph=DEMO_GRAPH))
    db.add(Template(name="智能客服工单处理", description="分类、置信度路由、知识库回复与人工兜底", category="customer_service", graph=DEMO_GRAPH, use_count=1268))
    db.add(Template(name="日报自动生成", description="聚合数据后生成管理层日报", category="data", graph=DEMO_GRAPH, use_count=842))
    db.add(Template(name="简历初筛助手", description="结构化解析候选人并输出匹配度", category="hr", graph=DEMO_GRAPH, use_count=596))
    db.commit()

