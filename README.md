# AgentFlow

AgentFlow is a portfolio-grade AI Agent workflow orchestration platform. It combines a visual React Flow editor with a FastAPI backend, persistent workflow versions, a DAG execution engine, node-level logs, model usage accounting, and a deterministic mock LLM mode.

## Highlights

- Visual trigger, Agent, condition, HTTP, notification, and output nodes.
- DAG cycle validation and topological execution.
- Published immutable workflow versions.
- PostgreSQL persistence with tenant-scoped data.
- Redis/Celery asynchronous execution in Docker; inline mode for local development.
- Mock Agent mode for a complete zero-key demo.
- Execution logs, token/cost analytics, templates, and audit-ready architecture.

## Local Development

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

Open `http://127.0.0.1:5173`. The frontend automatically uses `demo@agentflow.dev` / `demo1234`.

## Docker Compose

```powershell
docker compose up --build
```

- Product: `http://localhost:8080`
- API docs: `http://localhost:8000/docs`
- Health: `http://localhost:8000/health/live`

## Demo Flow

1. Inspect dashboard reliability and cost metrics.
2. Open `工作流构建器`, select a node, and edit its label.
3. Save and publish the workflow.
4. Click `试运行`.
5. Open `运行监控` to inspect persisted node logs and token cost.

## Architecture

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

## Verification

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q

cd ..\frontend
npm run build
```

## Resume Copy

**AgentFlow - Enterprise AI Agent Workflow Platform | Full-stack personal project**

- Built a visual multi-Agent workflow platform with React Flow and FastAPI, supporting graph validation, topological execution, conditional branches, retries, node logs, and workflow versioning.
- Designed PostgreSQL tenant isolation, Redis/Celery asynchronous execution, JWT authentication, SSE status streaming, and Docker Compose deployment.
- Implemented deterministic mock Agents and usage/cost analytics so reviewers can run the complete demo without paid API credentials.

## Honest Scope

Production billing, hundreds of third-party connectors, Kubernetes, collaborative editing, and full RAG administration remain roadmap items and are not represented as completed features.

