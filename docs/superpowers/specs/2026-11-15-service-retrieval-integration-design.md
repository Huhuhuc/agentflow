# 售后 Agent 业务检索接入设计

日期：2026-11-15  
状态：设计已确认，待实现  
目标：将已有政策索引接入售后 Agent 的 `search_policy` 工具，保留可核查证据、版本快照和词法降级能力。

## 1. 目标与边界

本轮完成一条可审计的业务检索路径：会话创建时固定租户可见的政策版本；Agent 检索时在相同快照范围内选择词法或 hybrid；返回结果仍使用原文证据 ID；索引不可用、模型未配置或向量计算失败时显式回退到词法；低于业务配置阈值时返回“资料不足”，不生成无依据结论。

本轮不做以下事情：

- 不引入 pgvector、独立向量数据库或新的后台队列；沿用现有 `PolicyIndex` 和 worker。
- 不改变工单人工确认、订单校验、政策版本变更拒绝和幂等规则。
- 不把 36 条合成查询得出的阈值自动用于真实租户资料；阈值由配置显式提供，缺省时不启用拒答。
- 不把向量分数展示为置信度，不向模型传递原始向量或内部索引细节。
- 不将 hybrid 设为默认；默认模式仍为 lexical。

## 2. 现有边界

`service_api.create_turn` 调用 `database_snapshot`，快照包含当前租户的订单、最高有效政策版本及带来源位置的原文块。`service_api.confirm` 会重新建立当前快照，并拒绝订单或被引用政策已变化的草稿。`business_agent.invoke("search_policy")` 是实际执行工具入口；目前租户资料路径只做主题过滤和 bigram 排序。

`PolicyIndex` 保存政策 ID、不可变 fingerprint、模型 revision、分块和已校验向量。索引分块目前可能与 800 字符业务快照块不同，因此不能假设 chunk ID 相同。接入层必须通过政策 ID、原文区间或完整文本映射回快照证据；无法安全映射时该索引只能标记不可用并走 lexical_fallback。

## 3. 配置与数据流

新增明确配置（名称按现有 Settings 风格实现）：

- `RETRIEVAL_MODE=lexical|hybrid`，默认 `lexical`。
- `RETRIEVAL_ABSTENTION_THRESHOLD`，可为空；为空时不依据分数拒答。
- `RETRIEVAL_MIN_INDEX_COVERAGE`，默认 1.0，要求本次快照内每个候选政策都有 ready 索引并完成映射。
- 使用现有 `EMBEDDING_MODEL_PATH`、`EMBEDDING_REVISION`，不自动下载模型。

业务快照增加内部检索元数据，不进入模型提示：

```text
retrieval: {
  requested_mode: "lexical" | "hybrid",
  effective_mode: "lexical" | "hybrid" | "lexical_fallback",
  policy_indexes: [{policy_id, index_id, model_revision, mapped_chunks, coverage}],
  threshold: number | null,
  fallback_reason: string | null
}
```

`knowledge` 仍是模型可引用的原文证据列表。内部元数据在构造工具请求前从 snapshot 剥离，防止模型伪造模式、索引 ID 或阈值。

一次 `search_policy` 的步骤：

1. 根据订单状态和主题确定候选政策，先做租户与快照版本过滤。
2. 若请求模式为 lexical，执行现有 bigram 排序。
3. 若请求模式为 hybrid，检查候选政策是否都有 ready 索引、revision 是否与配置一致、索引块能否映射到快照证据；任一条件失败则使用 lexical，并记录原因。
4. 对可用索引计算查询 embedding，与 lexical 前 20 和向量前 20 做固定 RRF 融合，返回最多 5 个快照证据。
5. 若配置了阈值且 top-1 分数低于阈值，返回空结果并标记 `abstained=true`；模型只能据此询问补充信息或转人工。阈值为空时不进行分数拒答。
6. 结果包含 `retrieval`、`fallback_reason`、`index_revision`、`abstained` 和候选证据 ID，轨迹保存这些字段；不返回向量本身。

## 4. 证据映射与版本安全

索引块映射到快照证据的优先级为：

1. 完整文本和政策 ID 唯一匹配；
2. 原文 `start/end` 坐标完全落在同一政策版本内；
3. 以上均无法确认时拒绝使用该索引，不用近似字符串拼接冒充证据。

快照只包含创建时已生效的每个 slug 最高有效版本。索引查询必须使用对应 `policy_id`，不能用旧版本向量补位。政策新版本没有 ready 索引时，整个候选集回退 lexical；不能混用新版本词法块和旧版本向量块。跨租户索引、未来版本、已撤回版本和不匹配 model revision 均视为不可用。

审批仍以快照中的证据 ID 和当前政策内容做二次校验。检索命中不绕过订单状态校验、政策适用性校验或人工确认。

## 5. 失败处理与可观测性

以下情况均不抛出无上下文的 500，而是保留工具结果并继续安全流程：模型未配置、索引缺失、索引覆盖不足、revision 不匹配、查询 embedding 超时、向量维度错误、阈值触发拒答。工具输出明确 `retrieval` 为 `lexical`、`hybrid` 或 `lexical_fallback`，并记录原因码。

运行轨迹的政策检索事件至少保存：请求 query、候选政策 ID、有效模式、索引 ID/revision、候选数、返回证据 ID、top-1 分数（内部字段）、阈值、是否拒答、耗时和回退原因。日志不保存 API 密钥或完整 embedding。

## 6. 测试验收

新增单元测试覆盖：

- lexical 默认路径与现有结果保持一致；
- hybrid 在完整 ready 索引和匹配 revision 时返回融合结果；
- 缺索引、映射失败、revision 不匹配、模型路径为空和向量异常均走 lexical_fallback；
- 阈值为空时不拒答，阈值命中时返回 abstained 且不能生成 answer/confirm_ticket；
- 新政策版本不会读取旧版本索引；撤回政策和未来生效政策不进入候选；
- 跨租户索引 ID 不会影响另一租户快照；
- 返回证据始终属于当前 run 的快照，伪造证据 ID 仍被拒绝；
- 审批前政策更新仍返回 409，重复确认仍保持幂等。

新增端到端测试使用现有 SQLite fixture，分别运行 lexical、hybrid-ready、hybrid-fallback 和 abstention 四条路径。PostgreSQL/Celery 仍沿用现有专项测试，不在本轮扩大为完整部署验收。

## 7. 交付口径

README 和业务说明继续声明：线上默认是 lexical，hybrid 是显式实验模式；当前 BGE 结果来自 36 条作者编写的合成查询，不能作为业务准确率。实现完成后只记录实际运行的测试数量、模式、回退次数和人工复核结果，不预填效果提升百分比。
