# Game Feedback Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 AgentFlow 改造成面向策划/运营的可视化零代码 AI 流程平台，并用“玩家反馈自动分流”跑通收集、分类、分发、验证闭环。

**Architecture:** 保留现有 FastAPI、SQLAlchemy、DAG engine、React Flow、SSE 和 Mock/真实 LLM 网关。新增反馈批次、反馈决策、验证记录领域数据；将业务节点映射到现有通用节点执行协议；前端按反馈批次、流程编排、运行监控和验证复盘组织页面。

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, SQLite/PostgreSQL, React, TypeScript, Vite, `@xyflow/react`, Recharts, Lucide, pytest.

---

### Task 1: 建立反馈领域模型与 API 合约

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_feedback_api.py`

- [ ] **Step 1: 写失败测试，锁定批次创建、CSV 校验和人工决策接口**

```python
def test_demo_batch_has_planner_fields(client, auth_headers):
    response = client.post("/api/v1/feedback-batches/demo", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["feedback_count"] > 0
    assert {"version", "channel", "player_text"}.issubset(body["sample_fields"])

def test_invalid_csv_returns_row_errors(client, auth_headers):
    response = client.post(
        "/api/v1/feedback-batches/import",
        headers=auth_headers,
        files={"file": ("feedback.csv", b"feedback_id,player_text\n1,\n", "text/csv")},
    )
    assert response.status_code == 422
    assert response.json()["errors"][0]["row"] == 2

def test_feedback_decision_can_be_corrected(client, auth_headers, feedback_id):
    response = client.patch(
        f"/api/v1/feedbacks/{feedback_id}/decision",
        headers=auth_headers,
        json={"category": "角色平衡", "owner_role": "战斗策划", "decision": "adopt"},
    )
    assert response.status_code == 200
    assert response.json()["owner_role"] == "战斗策划"
```

- [ ] **Step 2: 运行测试确认新接口尚不存在**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest tests/test_feedback_api.py -q`

Expected: FAIL with 404 responses or missing fixtures.

- [ ] **Step 3: 添加模型与 Pydantic schema**

在 `models.py` 增加 `FeedbackBatch`、`PlayerFeedback`、`FeedbackDecision`、`VerificationRecord`，均带 `tenant_id`；在 `schemas.py` 增加批次输出、导入错误、决策更新和验证请求/响应类型。`PlayerFeedback` 的 JSON 字段保存 `game_objects`、`evidence`、`classification` 与 `priority_breakdown`，避免本期引入迁移工具。

- [ ] **Step 4: 添加批次、反馈、决策和验证路由**

在 `main.py` 增加：

```text
POST /api/v1/feedback-batches/demo
POST /api/v1/feedback-batches/import
GET  /api/v1/feedback-batches
GET  /api/v1/feedback-batches/{id}
GET  /api/v1/feedbacks?batch_id={id}
PATCH /api/v1/feedbacks/{id}/decision
POST /api/v1/feedbacks/{id}/verification
```

CSV 只接受固定字段 `feedback_id,version,region,channel,player_text,reported_count,affected_players`；空文本、缺字段、UTF-8 解码失败和超过 500 行均返回行级错误且不创建可执行批次。所有查询按当前用户 `tenant_id` 限制。

- [ ] **Step 5: 运行测试并提交**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest tests/test_feedback_api.py -q`

Expected: PASS.

Commit: `git add backend/app/models.py backend/app/schemas.py backend/app/main.py backend/tests/test_feedback_api.py; git commit -m "feat: add player feedback domain APIs"`

### Task 2: 实现策划分类、优先级与路由节点

**Files:**
- Modify: `backend/app/engine.py`
- Modify: `backend/app/seed.py`
- Create: `backend/app/feedback.py`
- Modify: `backend/tests/test_engine.py`
- Create: `backend/tests/test_feedback_rules.py`

- [ ] **Step 1: 写失败的规则测试**

```python
def test_priority_breakdown_routes_high_risk_battle_issue():
    result = score_feedback({"severity": 1.0, "frequency": .9, "affected_scope": .8, "version_goal_relevance": 1.0})
    assert result["priority"] == "P0"
    assert result["breakdown"]["severity"] == .4

def test_owner_role_uses_gameplay_semantics():
    assert route_feedback({"category": "角色平衡"}) == "战斗策划"
    assert route_feedback({"category": "数值经济"}) == "数值策划"
    assert route_feedback({"category": "研发缺陷"}) == "研发"

def test_low_confidence_enters_human_review():
    assert route_feedback({"category": "角色平衡", "confidence": .42}) == "人工复核"
```

- [ ] **Step 2: 运行规则测试确认失败**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest tests/test_feedback_rules.py -q`

Expected: FAIL because `feedback.py` does not exist.

- [ ] **Step 3: 实现纯函数规则模块**

在 `feedback.py` 实现 `classify_feedback(text, metadata)`, `score_feedback(factors)` 和 `route_feedback(result)`。Mock 分类按关键词稳定返回战斗机制、角色平衡、关卡体验、数值经济、系统体验、研发缺陷或非有效反馈，并生成 `game_objects`、`evidence`、`confidence`。优先级公式固定为 `severity*.4 + frequency*.3 + affected_scope*.2 + version_goal_relevance*.1`，按阈值映射 P0/P1/P2/P3，同时返回四项 breakdown。

- [ ] **Step 4: 将领域节点接入 DAG 执行**

在 `engine.py` 的 `run_node` 支持 `feedback_batch`、`priority`、`route`、`human_review`、`verification`；批次节点读取 `execution.input_data["feedbacks"]`，分类和评分结果写入 context，低置信度返回 `needs_review=True`，最终结果保留每条反馈的证据和去向。沿用现有日志、重试、终点推导和 SSE，不改变通用节点行为。

- [ ] **Step 5: 更新种子流程为策划场景并运行全量后端测试**

将 `seed.py` 的 `DEMO_GRAPH` 改为“反馈批次 -> 分类 -> 优先级评分 -> 团队路由 -> 人工复核 -> 验证结果”，另加入 12 条覆盖战斗、数值、系统、研发的示例反馈和三个策划模板。

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest -q`

Expected: PASS.

Commit: `git add backend/app/engine.py backend/app/feedback.py backend/app/seed.py backend/tests/test_engine.py backend/tests/test_feedback_rules.py; git commit -m "feat: add planner feedback routing nodes"`

### Task 3: 重构前端为策划/运营工作台

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/App.css`
- Modify: `frontend/src/FlowNode.css`

- [ ] **Step 1: 增加领域 API 类型与调用函数**

在 `api.ts`/`App.tsx` 定义 `FeedbackBatch`、`PlayerFeedback`、`Decision`、`Verification` 类型，并封装 `/feedback-batches`、`/feedbacks` 和验证 API；保留现有认证和 workflow API。

- [ ] **Step 2: 将导航与总览改为策划语义**

导航调整为“决策总览、反馈批次、分流流程、运行追踪、验证复盘、流程模板”。总览显示 P0/P1 数量、战斗风险、待人工复核、平均分流时长、人工修正率和版本后反馈变化；保留 Token/成本作为运行可靠性指标。

- [ ] **Step 3: 添加反馈批次页面**

支持“加载示例”和 CSV 文件选择；展示版本、渠道、反馈数、错误行摘要。批次列表点击后进入分流结果表，表格显示玩家文本、分类、对象、置信度、证据、优先级和接收角色。

- [ ] **Step 4: 改造 React Flow Builder**

节点库显示“反馈批次、AI 分类、优先级评分、团队路由、人工复核、验证回写”；Inspector 显示业务配置和规则权重。保存、发布和试运行保留，试运行输入改为选中批次；SSE 事件将节点状态高亮并同步运行追踪。

- [ ] **Step 5: 添加人工决策与验证复盘**

结果行提供“修正分类、修改接收角色、采纳/驳回/待验证”。验证表单要求目标版本、调整方案和结论；复盘页用 Recharts 展示同类反馈变化、采纳率和验证完成率。

- [ ] **Step 6: 更新样式并验证构建**

采用现有 CSS 变量与 8px 以下圆角，保持桌面密度和移动端折叠；节点状态使用统一成功/运行/失败色。避免把业务指标塞进装饰卡片，确保表格与画布是首屏主要内容。

Run: `cd frontend; npm run build`

Expected: PASS with generated `dist` output.

Commit: `git add frontend/src/App.tsx frontend/src/api.ts frontend/src/App.css frontend/src/FlowNode.css; git commit -m "feat: build planner feedback workspace"`

### Task 4: 端到端演示、文档与质量门禁

**Files:**
- Modify: `README.md`
- Modify: `docs/demo-script.md`
- Modify: `docs/project-introduction.md`
- Modify: `backend/tests/test_api.py`
- Create: `backend/tests/test_feedback_e2e.py`

- [ ] **Step 1: 写端到端流程测试**

测试登录、创建示例批次、启动发布版流程、轮询执行完成、断言至少包含分类/评分/路由/验证日志，再提交一条人工决策和验证记录，最后断言 analytics 返回业务指标。

- [ ] **Step 2: 运行后端与前端验证**

Run: `cd backend; .\.venv\Scripts\python.exe -m pytest -q`

Run: `cd frontend; npm run build`

Expected: all backend tests pass and frontend build exits 0.

- [ ] **Step 3: 更新项目说明与面试演示脚本**

README 和项目介绍明确“复用难、不可观测”问题、竞品差异和策划闭环；演示脚本按“模板 -> 批次 -> 画布 -> SSE 监控 -> 人工复核 -> 版本验证”编排，并说明 Mock 模式无需 API Key。

- [ ] **Step 4: 执行浏览器验收**

启动后端 `python -m uvicorn app.main:app --reload` 与前端 `npm run dev`，在 `http://127.0.0.1:5173` 完成：加载示例、运行流程、查看节点状态、修正一条反馈、提交验证。检查 1440px、1024px 和移动宽度下无重叠、无空白画布、错误和空状态可见。

- [ ] **Step 5: 提交交付版本**

Commit: `git add README.md docs/demo-script.md docs/project-introduction.md backend/tests/test_api.py backend/tests/test_feedback_e2e.py; git commit -m "docs: complete planner feedback demo"`

## Self-Review

- **Spec coverage:** 竞品拆解由 Task 4 文档更新覆盖；批次/CSV/领域模型由 Task 1 覆盖；分类、优先级、路由和人工池由 Task 2 覆盖；页面、模板、SSE 和验证复盘由 Task 3 覆盖；异常与测试由 Task 1/2/4 覆盖。
- **Scope:** 仍是一个主场景和一套平台能力；外部连接器、多人协作和真实数值模拟明确排除。
- **Type consistency:** 后端使用 `FeedbackBatch`、`PlayerFeedback`、`FeedbackDecision`、`VerificationRecord`；前端使用对应的 `FeedbackBatch`、`PlayerFeedback`、`Decision`、`Verification` 展示类型，API 路径在 Task 1 与 Task 3 一致。
- **Placeholder scan:** 未使用 TBD、TODO、`implement later` 或未定义的函数名；每个实现步骤都有文件、命令和预期结果。
