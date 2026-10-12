# AgentFlow

## 企业售后工作台 v2

默认页面现支持持久会话、补充信息、租户订单CSV导入、政策文件与版本、可编辑审核工单、处理状态及服务端评测实验。首次点击「加载明确标注的演示数据」即可用Mock完成售后流程。

已接入独立Celery业务/评测队列，增加版本化增量建表、依赖就绪检查、普通登录及GitHub Actions配置。详细操作与验证边界见 [本轮交付说明](docs/service-agent-v2.md)。

## 企业服务 Agent 实习面试版

DeepSeek 接入：在 `backend/.env` 填写密钥，双击 `test-deepseek.bat` 验证一个真实任务。详细步骤和后续评测命令见 [DeepSeek 配置说明](docs/deepseek-setup.md)。

新增默认入口“企业服务 Agent”：订单查询、规则检索、多轮工具调用、证据引用、工单草稿、人工确认/拒绝、取消和失败后检查点恢复。支持无密钥 Mock 演示及真实模型工具调用。具体演示步骤、运行方式及实现边界见 [企业服务 Agent 说明](docs/business-agent.md)。

示例：“订单 A102 为什么无法退款？请生成申诉工单。” 数据为合成订单，检索为关键词匹配；工单保存在本地平台。尚未接入生产订单系统和向量 RAG。

## 反馈处理 Agent

主目录已增加反馈处理 Agent 工作台：真实模式使用 function calling 选择版本资料查询、相似反馈查询与工单草稿工具；Mock 模式提供明确标注的无密钥演示。支持固定运行快照、步骤与调用预算、逐步轨迹、人工确认及离线评估。详见 [实现与演示说明](docs/feedback-agent.md)。游戏策划平台的独立 worktree 尚未整体合并。

默认进入 Agent 工作台，提交反馈后可以检查检索证据、工具结果与待确认草稿。确认仅保存本项目工单，不调用外部系统。知识资料和评估样本为合成示例，检索为关键词匹配；不能将 Mock 评估写成真实模型准确率。

AgentFlow 是一个适合作品集展示的 AI Agent 工作流编排平台。项目将可视化 React Flow 编辑器、FastAPI 后端、持久化工作流版本、DAG 执行引擎、节点级日志、模型用量统计，以及确定性 Mock LLM 模式组合成一套完整的前后端工程。

## 项目与文档入口

- [项目介绍](docs/project-introduction.md)：项目定位、核心能力、技术方案、演示亮点与简历表述。
- [文档介绍](docs/documentation-guide.md)：仓库文档结构、推荐阅读顺序与各文档用途。

## 核心能力

- 可视化触发器、Agent、条件判断、HTTP、通知和输出节点。
- DAG 环检测与拓扑执行。
- 发布后不可变的工作流版本。
- 基于 PostgreSQL 的持久化存储，并按租户隔离数据。
- Docker 环境下使用 Redis/Celery 异步执行；本地开发支持 background task 异步执行模式。
- 真实 LLM 网关：通过 `llm_mode` 切换，OpenAI-compatible 模式支持 system/user 提示词模板、温度与 JSON 结构化输出；Mock 模式零 API Key 完整演示。
- LLM 调用具备指数退避重试：仅对 429/408 与 5xx 等瞬时故障及网络异常重试，并优先遵守服务端 `Retry-After`；鉴权、参数等确定性错误立即失败不空转。重试次数支持全局（`LLM_MAX_RETRIES`）与节点级（`config.max_retries`）配置，实际尝试次数写入节点日志。
- 执行终点由图结构推导（取无出边节点，优先 output 类型），条件分支跳过部分终点时仍能取到实际走通分支的结果。
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

**AgentFlow - AI 工作流与反馈处理 Agent | 全栈个人项目**

- 基于 React Flow 与 FastAPI 搭建可视化 AI 工作流平台，支持图结构校验、拓扑执行、条件分支、重试、节点日志和工作流版本管理。
- 设计 PostgreSQL 租户隔离、Redis/Celery 异步执行、JWT 鉴权、SSE 状态推送和 Docker Compose 部署方案。
- 实现真实/Mock 双模式 LLM 网关（OpenAI-compatible，支持提示词模板与 JSON 结构化输出），并按错误类型分级重试——瞬时故障指数退避且遵守 `Retry-After`，确定性错误快速失败；Mock 模式使面试官无需付费 API 凭证也能跑通完整演示。

## 诚实范围说明

生产级计费、数百个第三方连接器、Kubernetes、多人协同编辑，以及完整 RAG 管理后台仍属于路线图内容，本文档不会将它们描述为已完成功能。

## 企业服务 Agent：新增评测与崩溃恢复

双击 `evaluate-business.bat` 生成 Mock 开发集 JSON / CSV / Markdown 报告。在企业服务工作台底部「评测与人工复核」导入 JSON，可检查失败样本、逐条复核并导出。

业务执行现支持租约回收、检查点恢复、过期执行器写入校验及并发确认去重。真实模型评测需配置后端密钥，Mock 成绩不代表模型准确率。

完整运行命令、费用口径和恢复边界见 [企业 Agent 评测与可靠性](docs/business-evaluation-reliability.md)。
