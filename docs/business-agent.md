# 企业服务 Agent 面试演示

本次新增企业服务工作台，默认打开。React + FastAPI，复用现有 AgentRun、AgentFeedback、AgentTicket 表，无需修改旧表结构。后台启动时 create_all 创建缺失表。

## 启动

后端：在 backend 目录安装 requirements.txt，执行 `python -m uvicorn app.main:app --reload`。
前端：在 frontend 目录执行 `npm install`、`npm run dev`。
默认 Mock 模式无需密钥。真实调用需配置 OPENAI_API_KEY、OPENAI_BASE_URL、OPENAI_MODEL；在工作台选择真实模型。

## 演示顺序

1. 输入“订单 A101 的退款条件是什么”，观察订单查询、规则检索和带引用回答。
2. 输入“订单 A102 为什么无法退款？请生成申诉工单”，展开工具轨迹，检查订单已使用且签收12天的证据。
3. 点击人工确认，查看状态变为已创建工单；重复确认 API 返回同一工单。拒绝草稿后不能确认。
4. 输入“A999退款”，展示资料不足；输入没有订单号的问题，展示请求补充信息。
5. 在运行中取消，或在模型故障后从检查点重试；已完成的读取工具结果被保留。

## 实现和边界

- 三种工具：search_policy、get_order、draft_ticket；Pydantic 严格验证参数，未知工具被拒绝。
- 最多6轮、8次工具调用、12000 Token、单次运行时间预算；仅模型 API 有外部网络调用。
- 运行快照保留提示词、工具定义、规则及订单。逐轮保存消息与证据检查点，失败后显式恢复。
- 运行、工单按租户隔离。示例订单目录为各租户共享的合成数据，不是生产客户系统。
- 工具只能生成草稿，创建本地工单必须通过登录用户确认 API。数据库唯一约束与状态条件更新防止重复确认。
- Mock 使用规则选择工具，零真实模型 Token；真实模式使用模型 function calling。关键词检索不是向量 RAG；评测报告支持按手填单价估算费用，缺少完整用量时保持未知。
- 新增150秒执行租约、每5秒自动回收、旧执行器写入校验及最多三次执行尝试。恢复支持已持久化的轮次；未提交的模型请求可能重放。未接外部工单、MCP、上传知识库或任意 SQL。
- 固定业务评测集和界面人工复核功能见 [评测与可靠性说明](business-evaluation-reliability.md)。
- 测试验证业务状态和执行边界，不代表真实模型语义准确率；面试不要把 Mock 通过率写成模型任务成功率。

## 学习参考

- https://github.com/langchain-ai/langgraph ：状态、检查点、人工介入模式；当前运行器为项目自写实现。
- https://github.com/modelcontextprotocol/python-sdk ：后续统一工具接入参考，当前未接入。
- https://github.com/langfuse/langfuse ：后续追踪与评测参考，当前使用本地运行轨迹。

## 测试

`python -m pytest -q` 验证原工作流及新增企业流程。
`npm run build` 验证前端类型和打包。
新增测试包含6类业务样本、证据伪造、Token预算、故障后检查点恢复、确认幂等与拒绝后禁止创建。
