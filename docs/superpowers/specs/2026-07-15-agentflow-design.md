# AgentFlow 全栈设计规格

## 1. 项目目标

构建一个适合作品集展示、接近生产形态的 AI Agent 工作流编排平台。项目需要能够通过 Docker Compose 完整运行，并且在没有付费 API 凭证的情况下也能完成演示。

项目需要证明五类能力：

1. AI 产品定义与范围控制能力。
2. 可视化工作流设计与企业级 UX 能力。
3. DAG 执行引擎与异步后端工程能力。
4. 可靠的 LLM 集成、可观测性与人工兜底能力。
5. 产品分析、多租户治理与部署交付能力。

## 2. 目标用户

主要用户是企业中的非工程岗位运营人员，例如客服负责人、内容运营、HR 团队和数据分析师。

他们的核心任务是在不写代码的前提下自动化一个可重复流程，同时保留对成本、失败、权限和审计的控制。

## 3. 范围

### 3.1 已包含

- 支持租户隔离的注册与登录。
- 工作流列表、创建、编辑、版本管理、发布和归档。
- 可视化 React Flow 编辑器。
- 手动触发与 Webhook 触发。
- Agent、条件判断、HTTP 动作、通知和输出节点。
- DAG 校验与拓扑执行。
- 节点上下文插值。
- 重试、超时、取消和失败传播。
- 通过 OpenAI-compatible endpoint 接入真实 LLM 模式。
- 用于零配置演示和测试的确定性 Mock LLM 模式。
- PostgreSQL 持久化、Redis 消息/缓存、Celery worker。
- SSE 执行状态更新和节点级日志。
- 模板、监控看板、Token/成本分析和审计日志。
- 内置演示租户、账号、工作流、模板和执行记录。
- Docker Compose、环境变量模板、数据库迁移、测试和文档。
- 作品集 README 与可直接写入简历的项目描述。

### 3.2 暂缓

- 数百个生产级连接器。
- 计费收款与支付处理。
- Kubernetes 部署。
- 社区模板发布与审核。
- 完整的可视化 RAG 知识库管理后台。
- 多用户同时编辑同一个画布。

暂缓功能会保留扩展接口和路线图说明，但不会被描述成已经完成功能。

## 4. 系统架构

### 4.1 组件

- `web`：React 18、TypeScript、Vite、React Flow、Ant Design、Zustand、ECharts。
- `api`：FastAPI、Pydantic、SQLAlchemy、Alembic、JWT authentication。
- `worker`：Celery 执行 worker，与 API 共享领域服务。
- `postgres`：权威关系型数据存储。
- `redis`：Celery broker/result backend、短期执行事件和缓存。
- `llm_gateway`：后端内部实现的模型供应商无关接口。

### 4.2 后端边界

- `auth`：用户、租户、JWT、角色检查。
- `workflows`：工作流元数据、图结构校验、不可变发布版本。
- `engine`：图解析、拓扑调度、节点执行、上下文处理。
- `executions`：执行生命周期、取消、日志、事件发布。
- `llm`：供应商客户端、结构化输出校验、Token 与成本统计。
- `templates`：官方模板定义与实例化。
- `analytics`：执行量、可靠性、延迟、Token 和成本聚合指标。
- `audit`：管理操作与工作流变更的不可变记录。

API route 不直接持有工作流业务逻辑，而是委托给 service。节点实现使用统一接口，因此可以独立增加新的节点类型。

## 5. 核心领域模型

- `Tenant`：账号边界与套餐限制。
- `User`：租户成员，角色包括 admin、editor、viewer。
- `Workflow`：可变的元数据和草稿图。
- `WorkflowVersion`：不可变的已发布图快照。
- `Execution`：一次发布版或草稿工作流运行。
- `ExecutionLog`：一次节点尝试，记录 input、output、latency、error 和 cost。
- `Template`：可复用的图定义。
- `UsageRecord`：model、input/output tokens、estimated cost。
- `AuditLog`：actor、action、resource、timestamp 和结构化 details。

所有租户数据查询都必须按 `tenant_id` 限定范围。跨租户标识符返回 not found，避免暴露授权细节。

## 6. 工作流图契约

图结构以 JSON 形式存储，包含 `nodes`、`edges` 和编辑器 viewport 元数据。

每个节点包含：

- 稳定的节点 ID。
- 节点类型和展示名称。
- 节点位置。
- 类型专属配置。
- 可选的重试与超时策略。

发布时需要校验：

- MVP 工作流中恰好存在一个受支持的触发器。
- 不存在环。
- 所有边都引用已存在节点。
- 每个非终止节点都有有效的出边路径。
- 必填配置字段均已填写。
- 条件分支使用有效目标节点。
- 模板变量引用的是可用的上游输出。

## 7. 执行引擎

### 7.1 生命周期

`pending -> running -> success | failed | cancelled`

节点生命周期：

`pending -> queued -> running -> success | failed | skipped | cancelled`

### 7.2 执行流程

1. API 创建 execution 并将 worker task 入队。
2. Worker 加载不可变的图快照。
3. Engine 校验图结构并计算依赖关系。
4. 就绪节点开始执行；互相独立的节点可以并行执行。
5. 节点输出写入 execution context 并持久化。
6. 条件节点选择符合条件的下游分支；其他分支标记为 skipped。
7. 事件发布到 Redis，并由 API 通过 SSE 推送。
8. 终止输出和聚合用量写入数据库。

### 7.3 可靠性

- 可配置的节点超时时间。
- 可重试失败使用指数退避。
- 校验错误、授权错误或确定性的客户端错误不重试。
- HTTP action 节点在配置后支持 idempotency key。
- 每次节点尝试之间检查取消状态。
- 每次尝试都会持久化日志。
- 日志中会脱敏 secrets。

## 8. 节点类型

### Trigger

- 支持带 JSON input 的手动触发。
- 支持生成 path 和 shared secret 的 Webhook 触发。

### Agent

- 模型/供应商选择。
- System prompt 与模板化 user prompt。
- Temperature 与最大输出 Token。
- 可选 JSON output schema。
- 置信度阈值和兜底行为。
- 真实网关或 Mock 网关模式。

### Condition

- 基于上游 context 的规则组。
- 支持相等、比较、包含和存在性操作符。
- 默认分支。

### HTTP Action

- Method、URL、headers 和模板化 body。
- Timeout 与 retry policy。
- 可选 idempotency header。

### Notification

- 演示通知 sink 会作为 execution log 持久化。
- 为飞书、钉钉和企业微信保留 Webhook 扩展点。

### Output

- 选择并格式化工作流终止输出。

## 9. API 范围

- `/api/v1/auth/register`、`/login`、`/me`。
- `/api/v1/workflows` CRUD。
- `/api/v1/workflows/{id}/validate`、`/publish`、`/execute`。
- `/api/v1/workflows/{id}/versions`。
- `/api/v1/executions`、`/{id}`、`/{id}/logs`、`/{id}/cancel`。
- `/api/v1/executions/{id}/events` 用于 SSE。
- `/api/v1/templates`、`/{id}/instantiate`。
- `/api/v1/analytics/overview`、`/trends`、`/agents`。
- `/api/v1/audit-logs`。
- `/api/webhooks/{path}`。
- `/health/live` 和 `/health/ready`。

API 错误使用统一 envelope，包含 `code`、`message`、`details` 和 `request_id`。

## 10. 前端体验

首屏是登录后的应用工作台，而不是营销落地页。

主要视图：

- Dashboard：可靠性、执行量、成本、活跃工作流、近期失败。
- Workflows：可搜索列表，展示 draft/published 状态和操作。
- Builder：节点库、全宽画布、属性检查器、校验面板、运行控制。
- Templates：可筛选的模板卡片，支持预览和实例化。
- Executions：状态筛选和下钻。
- Execution detail：实时图高亮、节点时间线、input/output/error tabs。
- Analytics：执行趋势、成功率、延迟、Token 成本、模型对比。
- Team/audit：租户成员与审计表。

UI 风格需要安静、偏运营工具：克制的中性色、紧凑面板、无营销 hero、无装饰性渐变或嵌套卡片。图标使用现有组件库，所有纯图标操作都需要 tooltip。

## 11. 演示故事

种子工作流：`Smart Customer Service Ticket Processing`。

1. 手动输入创建一个客户工单。
2. Agent 对意图和置信度进行分类。
3. Condition 将普通问题路由到 answer Agent。
4. 低置信度或投诉分支创建人工审核通知。
5. Output 返回决策和回复内容。
6. Execution detail 展示实时节点进度、日志、延迟、Token 和成本。

Mock 模式会基于种子输入返回确定性结果，因此无需外部凭证也能完成完整演示。

## 12. 安全与治理

- 密码哈希与短生命周期 JWT access tokens。
- 按租户限定范围的 repository 方法。
- 发布、删除和审计访问需要角色检查。
- Webhook shared-secret 校验。
- 基于环境变量管理 secrets；仓库中不提交凭证。
- 敏感 header 和 prompt variable 脱敏。
- 结构化审计日志。
- 围绕认证和执行设置基础请求频率限制。

## 13. 测试

### Backend

- 图环、孤立边、无效分支和缺失配置测试。
- 拓扑执行与并行依赖测试。
- 重试、超时、取消、跳过分支和失败传播测试。
- 租户隔离和角色授权测试。
- 使用隔离数据库的 API 集成测试。
- 确定性 LLM gateway 契约测试。

### Frontend

- 图编辑和属性持久化。
- 校验错误与发布流程。
- 手动执行和实时状态更新。
- 执行日志下钻。
- 桌面端响应式与最低支持平板布局。

### End-to-End

- 使用种子账号登录。
- 实例化模板。
- 编辑并发布。
- 在 Mock 模式下执行。
- 观察 SSE 更新和最终分析指标。

## 14. 运维

Docker Compose 启动 web、API、worker、PostgreSQL 和 Redis。

启动顺序：

1. 等待数据库和 Redis ready。
2. 应用 Alembic migrations。
3. 加载幂等 seed data。
4. 启动 API 和 worker。
5. 开发环境通过 Vite 提供前端服务，最终交付使用生产容器构建。

健康检查暴露依赖 readiness。日志包含 request ID、execution ID、workflow ID、node ID、duration 和 error code。

## 15. 作品集交付物

- 可运行源代码。
- 架构图和执行流程图。
- 产品/工程 README。
- 基于 OpenAPI 的 API 文档。
- 内置演示数据和脚本化展示路径。
- 截图或短演示录屏指引。
- 简历短版和详细版项目描述。
- 覆盖设计决策和取舍的面试问答附录。

简历短版：

> AgentFlow - 企业级 AI Agent 工作流平台 | 全栈个人项目
> 基于 React Flow 与 FastAPI 搭建可视化多 Agent 工作流平台，实现 DAG 校验/执行、条件路由、重试、实时 SSE 日志、租户隔离、模型用量/成本分析和 Docker Compose 部署。设计真实/Mock LLM 网关，使完整产品演示无需付费凭证即可运行。

## 16. 成功标准

- 一条命令可以启动完整技术栈。
- 种子账号无需 API Key 即可完成演示故事。
- 已发布工作流的执行记录会持久化，并实时推送节点状态。
- 失败、重试和条件分支可见且可测试。
- 租户隔离测试通过。
- 核心后端和前端测试通过。
- README 能让评审在十分钟内运行并理解项目。
- 简历描述仅覆盖已经实现且验证过的功能。