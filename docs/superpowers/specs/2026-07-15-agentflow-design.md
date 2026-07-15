# AgentFlow Full-Stack Design

## 1. Objective

Build a portfolio-grade, production-shaped AI Agent workflow orchestration platform that is fully runnable through Docker Compose and demonstrable without paid API credentials.

The project must prove five capabilities:

1. AI product definition and scope control.
2. Visual workflow design and enterprise UX.
3. DAG execution engine and asynchronous backend engineering.
4. Reliable LLM integration with observability and human fallback.
5. Product analytics, multi-tenant governance, and deployment readiness.

## 2. Target Users

Primary users are non-engineering enterprise operators: customer-service leads, content operators, HR teams, and data analysts.

Their core job is to automate a repeatable process without writing code while retaining control over cost, failures, permissions, and auditability.

## 3. Scope

### 3.1 Included

- Tenant-aware registration and login.
- Workflow list, creation, editing, versioning, publishing, and archiving.
- Visual React Flow editor.
- Manual and webhook triggers.
- Agent, condition, HTTP action, notification, and output nodes.
- DAG validation and topological execution.
- Node context interpolation.
- Retry, timeout, cancellation, and failure propagation.
- Real LLM mode through an OpenAI-compatible endpoint.
- Deterministic mock LLM mode for zero-configuration demos and tests.
- PostgreSQL persistence, Redis messaging/cache, Celery workers.
- SSE execution updates and node-level logs.
- Templates, monitoring dashboard, token/cost analytics, and audit logs.
- Seeded demo tenant, account, workflows, templates, and executions.
- Docker Compose, environment template, migrations, tests, and documentation.
- Portfolio README and resume-ready project descriptions.

### 3.2 Deferred

- Two hundred production connectors.
- Billing collection and payment processing.
- Kubernetes deployment.
- Community template publishing and moderation.
- Full visual RAG knowledge-base administration.
- Simultaneous multi-user canvas editing.

Deferred features retain extension interfaces and roadmap documentation but are not represented as completed functionality.

## 4. Architecture

### 4.1 Components

- `web`: React 18, TypeScript, Vite, React Flow, Ant Design, Zustand, ECharts.
- `api`: FastAPI, Pydantic, SQLAlchemy, Alembic, JWT authentication.
- `worker`: Celery execution workers sharing domain services with the API.
- `postgres`: authoritative relational store.
- `redis`: Celery broker/result backend, short-lived execution events, and cache.
- `llm_gateway`: provider-neutral interface implemented inside the backend.

### 4.2 Backend Boundaries

- `auth`: users, tenants, JWT, role checks.
- `workflows`: workflow metadata, graph validation, immutable published versions.
- `engine`: graph parsing, topological scheduling, node execution, context handling.
- `executions`: execution lifecycle, cancellation, logs, event publication.
- `llm`: provider clients, structured output validation, token and cost accounting.
- `templates`: official template definitions and instantiation.
- `analytics`: aggregated execution, reliability, latency, token, and cost metrics.
- `audit`: immutable records of administrative and workflow mutations.

No API route owns workflow logic directly; routes delegate to services. Node implementations use a common interface so new node types can be added independently.

## 5. Core Domain Model

- `Tenant`: account boundary and plan limits.
- `User`: tenant member with admin, editor, or viewer role.
- `Workflow`: mutable metadata and draft graph.
- `WorkflowVersion`: immutable published graph snapshot.
- `Execution`: one run of a published or draft workflow.
- `ExecutionLog`: one node attempt with input, output, latency, error, and cost.
- `Template`: reusable graph definition.
- `UsageRecord`: model, input/output tokens, estimated cost.
- `AuditLog`: actor, action, resource, timestamp, and structured details.

Every tenant-owned query is scoped by `tenant_id`. Cross-tenant identifiers return not found rather than exposing authorization details.

## 6. Workflow Graph Contract

The graph is stored as JSON with `nodes`, `edges`, and editor viewport metadata.

Each node contains:

- Stable node ID.
- Node type and display name.
- Position.
- Type-specific configuration.
- Optional retry and timeout policy.

Publishing validates:

- Exactly one supported trigger for MVP workflows.
- No cycles.
- All edges reference existing nodes.
- Every non-terminal node has a valid outgoing path.
- Required configuration fields are present.
- Condition branches use valid target nodes.
- Template variables reference available upstream output.

## 7. Execution Engine

### 7.1 Lifecycle

`pending -> running -> success | failed | cancelled`

Node lifecycle:

`pending -> queued -> running -> success | failed | skipped | cancelled`

### 7.2 Flow

1. API creates an execution and enqueues the worker task.
2. Worker loads an immutable graph snapshot.
3. Engine validates the graph and computes dependencies.
4. Ready nodes execute; independent nodes may run in parallel.
5. Node output is written to execution context and persisted.
6. Condition nodes select eligible downstream branches; other branches are skipped.
7. Events are published to Redis and streamed by the API over SSE.
8. Terminal output and aggregate usage are committed.

### 7.3 Reliability

- Configurable node timeout.
- Exponential retry for retryable failures.
- No retry for validation, authorization, or deterministic client errors.
- Idempotency key for HTTP action nodes when configured.
- Cancellation checked between node attempts.
- Logs persist for every attempt.
- Secrets are redacted from logs.

## 8. Node Types

### Trigger

- Manual trigger with JSON input.
- Webhook trigger with generated path and shared secret.

### Agent

- Model/provider selection.
- System prompt and templated user prompt.
- Temperature and maximum output tokens.
- Optional JSON output schema.
- Confidence threshold and fallback behavior.
- Real or mock gateway mode.

### Condition

- Rule groups over upstream context.
- Operators for equality, comparison, containment, and existence.
- Default branch.

### HTTP Action

- Method, URL, headers, and templated body.
- Timeout and retry policy.
- Optional idempotency header.

### Notification

- Demo notification sink persisted as an execution log.
- Webhook extension point for Feishu, DingTalk, and WeCom.

### Output

- Selects and formats terminal workflow output.

## 9. API Surface

- `/api/v1/auth/register`, `/login`, `/me`.
- `/api/v1/workflows` CRUD.
- `/api/v1/workflows/{id}/validate`, `/publish`, `/execute`.
- `/api/v1/workflows/{id}/versions`.
- `/api/v1/executions`, `/{id}`, `/{id}/logs`, `/{id}/cancel`.
- `/api/v1/executions/{id}/events` for SSE.
- `/api/v1/templates`, `/{id}/instantiate`.
- `/api/v1/analytics/overview`, `/trends`, `/agents`.
- `/api/v1/audit-logs`.
- `/api/webhooks/{path}`.
- `/health/live` and `/health/ready`.

API errors use a consistent envelope containing `code`, `message`, `details`, and `request_id`.

## 10. Frontend Experience

The first screen is the authenticated application dashboard, not a marketing page.

Primary views:

- Dashboard: reliability, executions, cost, active workflows, recent failures.
- Workflows: searchable list with draft/published status and actions.
- Builder: node library, full-width canvas, property inspector, validation panel, run controls.
- Templates: filterable repeated template cards with preview and instantiate action.
- Executions: status filters and drill-down.
- Execution detail: live graph highlighting, node timeline, input/output/error tabs.
- Analytics: execution trend, success rate, latency, token cost, model comparison.
- Team/audit: tenant members and audit table.

The UI is quiet and operational: restrained neutral palette, compact panels, no marketing hero, no decorative gradients or nested cards. Icons use the existing component library. All icon-only actions have tooltips.

## 11. Demo Story

Seed workflow: `Smart Customer Service Ticket Processing`.

1. Manual input creates a customer ticket.
2. Agent classifies intent and confidence.
3. Condition routes normal questions to an answer Agent.
4. Low-confidence or complaint branches create a manual-review notification.
5. Output returns the decision and response.
6. Execution detail shows live node progress, logs, latency, tokens, and cost.

Mock mode returns deterministic results based on seeded inputs, allowing the complete demo without external credentials.

## 12. Security and Governance

- Password hashing and short-lived JWT access tokens.
- Tenant-scoped repository methods.
- Role checks for publishing, deletion, and audit access.
- Webhook shared-secret verification.
- Environment-based secrets; no committed credentials.
- Sensitive header and prompt-variable redaction.
- Structured audit logging.
- Basic request rate limits around authentication and execution.

## 13. Testing

### Backend

- Graph cycle, orphan edge, invalid branch, and missing configuration tests.
- Topological execution and parallel dependency tests.
- Retry, timeout, cancellation, skipped branch, and failure propagation tests.
- Tenant isolation and role authorization tests.
- API integration tests using an isolated database.
- Deterministic LLM gateway contract tests.

### Frontend

- Graph editing and property persistence.
- Validation errors and publish flow.
- Manual execution and live status updates.
- Execution log drill-down.
- Responsive desktop and minimum supported tablet layout.

### End-to-End

- Login with seed account.
- Instantiate template.
- Edit and publish.
- Execute in mock mode.
- Observe SSE updates and final analytics.

## 14. Operations

Docker Compose starts web, API, worker, PostgreSQL, and Redis.

Startup sequence:

1. Wait for database and Redis readiness.
2. Apply Alembic migrations.
3. Load idempotent seed data.
4. Start API and worker.
5. Serve frontend through Vite in development and a production container build for final delivery.

Health checks expose dependency readiness. Logs include request ID, execution ID, workflow ID, node ID, duration, and error code.

## 15. Portfolio Deliverables

- Runnable source code.
- Architecture and execution-flow diagram.
- Product/engineering README.
- API documentation through OpenAPI.
- Seeded demo and scripted presentation path.
- Screenshots or short demo recording guidance.
- Resume copy in short and detailed versions.
- Interview question-and-answer appendix covering design decisions and tradeoffs.

Resume short version:

> AgentFlow - Enterprise AI Agent Workflow Platform | Full-stack personal project
> Built a visual multi-Agent workflow platform with React Flow and FastAPI, implementing DAG validation/execution, conditional routing, retries, live SSE logs, tenant isolation, model usage/cost analytics, and Docker Compose deployment. Designed real/mock LLM gateways so the complete product demo runs without paid credentials.

## 16. Success Criteria

- One command starts the full stack.
- Seed account can complete the demo story without API keys.
- Published workflow executions persist and stream node status in real time.
- Failures, retries, and condition branches are visible and testable.
- Tenant isolation tests pass.
- Core backend and frontend tests pass.
- README enables a reviewer to run and understand the project in under ten minutes.
- Resume claims are limited to implemented and verified features.

