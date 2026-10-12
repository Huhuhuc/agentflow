import { useState } from 'react'

type Row = {
  id: string; repeat: number; text: string; contract_pass: boolean;
  expected_action: string; actual_action: string | null; latency_ms: number;
  error: string | null; result: unknown; trace: unknown[];
  human_review: { status: string; rubric: string; factual_correct: boolean | null; notes: string }
}
type Report = {
  schema: string; mode: string; model: string; split: string; dataset_sha256: string;
  metrics: Record<string, number | null>; rows: Row[]; [key: string]: unknown
}

function parseReport(value: unknown): Report {
  if (!value || typeof value !== 'object') throw new Error('请选择评测命令导出的 JSON 报告')
  const r = value as Report
  if (r.schema !== 'business-eval-v1' || !['mock', 'openai'].includes(r.mode) || typeof r.model !== 'string' || typeof r.split !== 'string' || typeof r.dataset_sha256 !== 'string' || !r.metrics || typeof r.metrics !== 'object' || !Array.isArray(r.rows) || !r.rows.length || r.rows.length > 60) throw new Error('报告格式或样本数量不正确')
  if (!Object.values(r.metrics).every(v => v === null || typeof v === 'number' && Number.isFinite(v))) throw new Error('指标格式不正确')
  for (const row of r.rows) {
    if (!row || typeof row.id !== 'string' || typeof row.text !== 'string' || typeof row.expected_action !== 'string' || !(row.actual_action === null || typeof row.actual_action === 'string') || typeof row.repeat !== 'number' || typeof row.contract_pass !== 'boolean' || typeof row.latency_ms !== 'number' || !(row.error === null || typeof row.error === 'string') || !Array.isArray(row.trace) || !row.human_review || typeof row.human_review.rubric !== 'string' || typeof row.human_review.notes !== 'string' || ![true, false, null].includes(row.human_review.factual_correct)) throw new Error('样本或复核信息格式不正确')
  }
  return r
}

export default function BusinessEvaluation() {
  const [report, setReport] = useState<Report | null>(null)
  const [error, setError] = useState('')
  const [failuresOnly, setFailuresOnly] = useState(false)
  const review = (index: number, correct: boolean | null, notes?: string) => setReport(current => current ? { ...current, rows: current.rows.map((row, i) => i === index ? { ...row, human_review: { ...row.human_review, status: correct === null ? 'pending' : 'reviewed', factual_correct: correct, notes: notes ?? row.human_review.notes } } : row) } : null)
  const reviewed = report?.rows.filter(r => r.human_review.factual_correct !== null).length ?? 0
  const exportReview = () => {
    if (!report) return
    const complete = reviewed === report.rows.length
    const output = { ...report, reviewed_at: new Date().toISOString(), metrics: { ...report.metrics,
      human_review_pending: report.rows.length - reviewed,
      semantic_success_rate: complete ? report.rows.filter(r => r.human_review.factual_correct === true).length / report.rows.length : null,
      end_to_end_success_rate: complete ? report.rows.filter(r => r.contract_pass && r.human_review.factual_correct === true).length / report.rows.length : null
    } }
    const url = URL.createObjectURL(new Blob([JSON.stringify(output, null, 2)], { type: 'application/json' }))
    const link = document.createElement('a'); link.href = url; link.download = `business-${report.mode}-${report.split}-reviewed.json`; link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  return <section className="agent-card">
    <h3>评测与人工复核</h3>
    <p>在 backend 目录运行下方命令，导入生成的 JSON。支持真实模型报告；模型密钥保留在后端配置中。</p>
    <pre style={{ overflowX: 'auto' }}>{'.\\.venv\\Scripts\\python.exe -m app.business_evaluation --mode mock --split dev --output evaluation/reports/business-dev.json'}</pre>
    <p>真实评测将 <code>--mode mock</code> 改为 <code>--mode openai</code>，首次可加 <code>--limit 1</code> 检查连接。测试集使用 <code>--split test</code>；重复实验使用 <code>--repeats 3</code>。</p>
    <label>导入评测报告<input type="file" accept=".json,application/json" onChange={async e => {
      const file = e.target.files?.[0]; if (!file) return
      setError('')
      try { if (file.size > 8 * 1024 * 1024) throw new Error('报告超过 8 MB'); setReport(parseReport(JSON.parse(await file.text()))) }
      catch (err) { setError(String(err)) }
      e.target.value = ''
    }} /></label>
    {error && <p className="agent-error" role="alert">{error}</p>}
    {report && <>
      <p><b>{report.mode === 'mock' ? 'Mock 契约测试 · 不代表模型能力' : '真实模型评测'}</b> · {report.model} · {report.split} · {report.rows.length} 次运行</p>
      <p>契约通过率 {((report.metrics.contract_pass_rate ?? 0) * 100).toFixed(1)}% · P95 {report.metrics.p95_ms ?? '未知'} ms · 估算费用 {report.metrics.estimated_cost ?? '未计价 / 用量不完整'}</p>
      <p>人工复核 {reviewed}/{report.rows.length}。自动引用检查仅核对来源 ID，回答是否符合业务事实由下方复核判定。复核结果在导出后保存。</p>
      <button onClick={exportReview}>导出含复核记录的 JSON</button>
      <label style={{ display: 'block', margin: '12px 0' }}><input type="checkbox" checked={failuresOnly} onChange={e => setFailuresOnly(e.target.checked)} /> 只看契约失败或人工判错样本</label>
      {report.rows.map((row, index) => (!failuresOnly || !row.contract_pass || row.human_review.factual_correct === false) && <details className="agent-trace" key={`${row.id}-${row.repeat}`}>
        <summary>{row.id} · 第 {row.repeat} 次 · {row.contract_pass ? '契约通过' : '契约失败'} · {row.text}</summary>
        <p>预期：{row.expected_action}；实际：{row.actual_action ?? '无结果'}；耗时：{row.latency_ms} ms</p>
        <p>事实复核标准：{row.human_review.rubric}</p>
        {row.error && <p className="agent-error">{row.error}</p>}
        <pre>{JSON.stringify(row.result, null, 2)}</pre>
        <label>事实是否正确<select value={row.human_review.factual_correct === null ? 'pending' : String(row.human_review.factual_correct)} onChange={e => review(index, e.target.value === 'pending' ? null : e.target.value === 'true')}><option value="pending">待人工复核</option><option value="true">正确</option><option value="false">错误</option></select></label>
        <label>复核说明<textarea rows={2} value={row.human_review.notes} onChange={e => review(index, row.human_review.factual_correct, e.target.value)} /></label>
        <details><summary>工具调用与模型耗时</summary><pre>{JSON.stringify(row.trace, null, 2)}</pre></details>
      </details>)}
    </>}
  </section>
}
