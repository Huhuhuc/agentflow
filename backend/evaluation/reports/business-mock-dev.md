# 企业服务 Agent 评测
模式：mock；模型：deterministic-demo；分组：dev

自动检查仅衡量契约；事实正确性仍需人工复核。Mock 不代表真实模型能力。

```json
{
  "execution_ok_rate": 1.0,
  "action_correct_rate": 0.75,
  "tool_contract_correct_rate": 0.8333333333333334,
  "citation_correct_rate": 1.0,
  "contract_pass_rate": 0.75,
  "cases": 12,
  "p50_ms": 1,
  "p95_ms": 2,
  "estimated_cost": null,
  "total_tokens": null,
  "usage_complete_cases": 0,
  "semantic_success_rate": null,
  "human_review_pending": 12
}
```

## 失败样本
- dev-08 / 第1轮：A102 退款需要审核吗？不要生成工单。；预期 answer，实际 confirm_ticket；错误：自动契约检查未通过
- dev-10 / 第1轮：A101 和 A102 的退款问题，请为其中一个创建工单。；预期 needs_information，实际 confirm_ticket；错误：自动契约检查未通过
- dev-11 / 第1轮：A103 尚未签收，退款条件适用吗？；预期 needs_information，实际 answer；错误：自动契约检查未通过