# DeepSeek 接入与后续改进

## 1. 在本地填写密钥

打开项目的 `backend/.env`。已预填：

```dotenv
OPENAI_API_KEY=
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_MODEL=deepseek-flash
LLM_MODE=mock
```

进入 [DeepSeek 开放平台](https://platform.deepseek.com/) 创建 API Key，并确认账户具备调用额度。把密钥粘贴到第一行等号后面，保存即可；不要发到聊天或提交到 Git。项目忽略 `.env` 文件。

变量名沿用 `OPENAI_*`，表示兼容接口配置，实际使用的是 DeepSeek 密钥和服务器。这里的 `LLM_MODE=mock` 保留工作流节点的默认演示模式；企业 Agent 的真实模式由界面选择或评测命令 `--mode openai` 显式开启。

本次已核对 [官方首次调用文档](https://api-docs.deepseek.com/zh-cn/)：接口地址为 `https://api.deepseek.com`，使用模型名 `deepseek-flash`。如果供应商后续变更模型名，以官方文档及账号可用模型为准。

## 2. 验证一个真实 Agent 任务

双击项目根目录 `test-deepseek.bat`。它先检查本地配置，然后发送**一个合成业务任务**，验证订单查询、政策检索、多轮工具调用和结构化回答；会使用 API 额度，不自动跑完整数据集。

成功应显示 `contract_pass: true`，并生成：

```text
backend/evaluation/reports/deepseek-smoke.json
backend/evaluation/reports/deepseek-smoke.csv
backend/evaluation/reports/deepseek-smoke.md
```

配置存在不等于认证成功。只有真实请求通过才能确认连接正常；自动契约通过仍需核查回答内容。

只检查本地配置、不联网时，在 backend 目录运行：

```powershell
.\.venv\Scripts\python.exe -m app.check_model
```

常见错误：401 检查密钥；402 检查余额；400/404 检查模型名及参数；429 等待后重试；超时或5xx检查网络和供应商状态。不要反复执行完整评测来排查认证失败。

## 3. 在页面使用

如果后端已在运行，关闭旧后端进程，再重新启动项目，让 `.env` 生效。修改 `.env` 不会自动改变运行中进程的配置。

打开 `http://127.0.0.1:5173`，登录后进入「企业服务 Agent」，把执行方式切换为「真实模型」，输入：

> 订单 A102 为什么需要人工审核退款？请生成申诉工单。

先检查证据与草稿，再按需点击人工确认。创建的仍是平台内演示工单。

## 4. 用真实结果继续迭代

单样本成功后，在 backend 目录运行完整开发集：

```powershell
.\.venv\Scripts\python.exe -m app.business_evaluation --mode openai --split dev --output evaluation/reports/deepseek-dev-v1.json
```

把 JSON 导入页面底部「评测与人工复核」，检查否定建单、订单歧义、政策适用性、虚构依据等案例。记录错误和事实复核结论，然后导出。

后续针对失败样本修改提示词或工具约束后，再跑同一组数据：

```powershell
.\.venv\Scripts\python.exe -m app.business_evaluation --mode openai --split dev --compare evaluation/reports/deepseek-dev-v1.json --output evaluation/reports/deepseek-dev-v2.json
```

开发集稳定、代码冻结后才运行测试集，避免用测试集反复调参：

```powershell
.\.venv\Scripts\python.exe -m app.business_evaluation --mode openai --split test --repeats 3 --output evaluation/reports/deepseek-test-v2.json
```

上面最后一条会执行36次 Agent 任务。每个任务可能包含多次 API 请求。先根据单样本实际用量决定是否执行。费用估算需另填输入和输出每百万 Token 单价；没有价格或完整用量时费用为空。

## 本次实际改动及边界

- 固定从 backend/.env 读取配置，支持 UTF-8 BOM，避免启动目录不同导致配置失效。
- 对官方 DeepSeek 端点显式发送 `thinking: {type: disabled}`，使用非思考模式。当前运行器不实现思考历史回传，因此不宣称支持 DeepSeek 思考模式。相关约定见 [官方思考模式文档](https://api-docs.deepseek.com/zh-cn/guides/thinking_mode/) 和 [工具调用文档](https://api-docs.deepseek.com/zh-cn/guides/tool_calls/)。
- 改进工具调用提示词，并兼容完整 JSON 代码块包装；无效 JSON 仍明确失败。
- 明确拒绝建单时，不生成草稿；出现多个不同订单号时，按当前单订单流程要求澄清。
- 退款规则只适用于已签收订单，配送规则只适用于运输中订单。工具调用和最终回答均校验订单与规则的对应关系。
- 防护采用当前合成订单和中文场景的保守规则，不是通用语义分类器；复杂否定、多订单批处理和更多政策需另行扩展与评测。

原开发集保持不变，Mock 契约检查从9/12提升到12/12；71项后端测试通过。该成绩是规则演示与契约检查，不是 DeepSeek 真实准确率。配置密钥并完成真实调用后，才能获得真实模型结果。
