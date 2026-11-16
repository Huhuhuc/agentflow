# RAG 索引基础模块：2026-11-02

发布前最终回归：**98 passed、1 skipped**。跳过 PostgreSQL 专项（本地未配置服务），已有弃用警告未清零。本次修复了跨 embedding revision 错误领取任务，并隔离了新增索引 API 测试中无关业务扫描器对单连接 SQLite 的干扰。业务恢复测试保持原有执行方式。前端未修改，未在本轮重新执行浏览器验收。

本轮实现设计稿的 M1 子步骤，尚未完成 M0/M1 全部交付。

验证：`python -m pytest -q --disable-warnings`，93 passed、1 skipped（2026-11-02）。本轮新增 9 项索引测试。跳过项为需额外环境的 PostgreSQL 测试，本轮不声称真实 PostgreSQL/Celery 验收完成；现有 datetime 等弃用警告仍保留。`git diff --check` 通过。

- `app.policy_index` 提供分块、幂等索引登记、原子领取、120 秒租约、最多三次尝试、旧执行器隔离和完整向量发布。
- `003_policy_indexes` 为增量建表迁移，不修改政策、工单或历史运行。
- `enqueue` 由调用方提交事务；`claim/finish/retry` 自行提交，应在独立索引 Session 使用。
- `run` 接受 embedding 回调 `(texts, immutable_revision) -> list[list[float]]`，异常保存错误类型，不保存可能包含密钥的完整异常消息。
- 非有限数、零向量、数量/维度不一致不发布 ready；向量在完整校验后归一化并一次事务写入。

当前已将索引生命周期接入售后 Agent 的显式 `hybrid` 实验路径：工作台可显示实际检索模式、回退原因和拒答状态；默认业务仍为词法检索。索引检索只使用当前租户快照中 ready 且 revision 匹配的记录，测试使用明确的合成向量，不能声称生产语义检索效果。本轮未调用付费模型，也未下载 embedding 权重。

分块当前为保留原文位置的 400 字符 / 40 字符重叠基线，独立于现有 800 字符业务快照；不是最终 tokenizer 分块。生产适配器必须加入 tokenizer 上限、输入大小、维度与模型 revision 校验；索引来源政策不可跨租户访问。

过期租约在下一次领取时回收；最后一次租约超时在下一次领取时置 failed。没有后台扫描器时不会自动推进。重试为显式调用，不包含自动退避或 broker 补发。生产接入前必须补齐调度与有上限的 embedding 超时。

后续顺序：真实 embedding 权重与哈希校验 → 自动建索引和队列恢复 → PostgreSQL/Celery 部署验收 → 用真实租户资料校准拒答阈值。当前接入设计见 `superpowers/specs/2026-11-15-service-retrieval-integration-design.md`。

## 第二轮：索引 API 与本地 embedding 适配

新增接口（均需登录）：

- `GET /api/v1/service/policies/{policy_id}/indexes`：查看本租户政策的索引状态，不返回向量和租约 token。
- `POST /api/v1/service/policies/{policy_id}/indexes`：admin/staff 显式创建索引任务；未配置 embedding 返回 503。任务持久化为 pending，接口不会立即运行模型。
- `POST /api/v1/service/indexes/{index_id}/retry`：失败且未耗尽三次尝试时重新排队；不重置次数。

本地配置新增 `EMBEDDING_MODEL_PATH`（已下载的本地 SentenceTransformer 模型目录）和 `EMBEDDING_REVISION`（操作者记录的固定模型版本标识）。当前未自动校验文件哈希，修改目录内容后必须更换版本并重新索引；不要把标签当成内容完整性证明。

`python -m app.index_worker` 显式执行最多 10 个 pending / 过期任务。需要自行安装可兼容的可选 `sentence-transformers` 依赖并准备模型；本轮没有更改默认依赖或下载权重。适配器只允许本地文件、CPU 推理和非远程代码加载；按 tokenizer 检查超长块，发现超限报错而非截断。真实 embedding 尚未实测。

这仍是分阶段实现：政策导入不会自动索引，尚无后台索引扫描器和生产级 broker 派发；查询 embedding 已有有界超时，超时或索引不完整会安全回退到词法。批处理失败可通过 API 查看错误类型并重试，默认业务仍走原词法检索。

新增三项测试验证 API 创建/查询/幂等、租户和角色限制，以及适配器版本/超长输入拒绝。使用合成 embedding 与 tokenizer，不代表 BGE 实测结果。原始第一轮说明保留用于追踪实现顺序。

## 第三轮：离线检索与拒答评测（2026-11-14）

新增独立离线基准 `python -m evaluation.retrieval_benchmark`，使用本地 `BAAI/bge-small-zh-v1.5` 权重比较词法、向量与 RRF 混合排序。每个策略的拒答阈值只在 dev split 上按 balanced outcome rate 校准，再冻结到 test split；test 不参与阈值选择。结果及逐条得分保存在 `backend/evaluation/reports/retrieval-bge-abstention-2026-11-14.json`，便于复核。

本次 test 共 18 条（15 条可回答、3 条无答案）。三种检索的 Recall@5 均为 15/15，但拒答结果不同：词法正确回答 13/15、正确拒答 3/3；向量正确回答 14/15、正确拒答 3/3；混合检索正确回答 14/15，却对 3 条无答案中的 2 条误答。详细阈值、覆盖率、误答率和误拒率见 [离线检索评测](retrieval-offline-evaluation.md)。这说明 top-5 找到正确条款与系统能否识别“无依据”是不同指标，当前证据不支持把混合检索设为更可靠的业务默认项。

数据只有 36 条作者编写的合成查询，dev/test 各 18 条且按资料组隔离；每个 split 仅有 3 条无答案探针，标签没有独立复核，不做显著性或泛化结论。评测脚本不调用生成模型。该结果只验证离线排序分数阈值流程，不能替代真实租户资料验收。当前业务接入由端到端测试覆盖 hybrid-ready、hybrid-fallback、超时回退和 abstention；完整后端测试结果以最近一次 CI/本地运行记录为准。
