# AgentFlow

AgentFlow 是一个适合作品集展示的 AI Agent 工作流编排平台。项目将可视化 React Flow 编辑器、FastAPI 后端、持久化工作流版本、DAG 执行引擎、节点级日志、模型用量统计，以及确定性 Mock LLM 模式组合成一套完整的前后端工程。

## 项目与文档入口

- [项目介绍](docs/project-introduction.md)：项目定位、核心能力、技术方案、演示亮点与简历表述。
- [文档介绍](docs/documentation-guide.md)：仓库文档结构、推荐阅读顺序与各文档用途。

## 核心能力

- 可视化触发器、Agent、条件判断、HTTP、通知和输出节点。
- DAG 环检测与拓扑执行。
- 发布后不可变的工作流版本。
- 基于 PostgreSQL 的持久化存储，并按租户隔离数据。
- Docker 环境下使用 Redis/Celery 异步执行；本地开发支持 inline 执行模式。
- Mock Agent 模式支持零 API Key 完整演示。
- 执行日志、Token/成本分析、模板能力，以及便于审计的系统架构。

## 本地开发

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

```powershell
cd frontend
npm install
npm run dev
```

打开 `http://127.0.0.1:5173`。前端会自动使用演示账号 `demo@agentflow.dev` / `demo1234`。

## Docker Compose

```powershell
docker compose up --build
```

- 产品页面：`http://localhost:8080`
- API 文档：`http://localhost:8000/docs`
- 健康检查：`http://localhost:8000/health/live`

## 演示流程

1. 查看总览看板中的可靠性指标和模型成本指标。
2. 打开 `工作流构建器`，选择一个节点并编辑节点名称。
3. 保存并发布工作流。
4. 点击 `试运行`。
5. 打开 `运行监控`，查看持久化节点日志和 Token 成本。

## 系统架构

```text
React/Vite/React Flow
        |
   FastAPI REST + SSE
        |
Workflow services + DAG engine
        |
PostgreSQL ---- Redis/Celery
        |
OpenAI-compatible / deterministic mock gateway
```

## 验证

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q

cd ..\frontend
npm run build
```

## 简历描述

**AgentFlow - 企业级 AI Agent 工作流平台 | 全栈个人项目**

- 基于 React Flow 与 FastAPI 搭建可视化多 Agent 工作流平台，支持图结构校验、拓扑执行、条件分支、重试、节点日志和工作流版本管理。
- 设计 PostgreSQL 租户隔离、Redis/Celery 异步执行、JWT 鉴权、SSE 状态推送和 Docker Compose 部署方案。
- 实现确定性 Mock Agent 与用量/成本分析能力，使面试官无需付费 API 凭证也能跑通完整演示。

## 诚实范围说明

生产级计费、数百个第三方连接器、Kubernetes、多人协同编辑，以及完整 RAG 管理后台仍属于路线图内容，本文档不会将它们描述为已完成功能。
