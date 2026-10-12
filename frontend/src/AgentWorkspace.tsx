import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import './AgentWorkspace.css'

type Feedback = { id: string; text: string; version: string }
type Trace = { step: number; kind: string; status: string; name?: string; duration_ms?: number; tokens?: number; attempts?: number; error?: string; arguments?: unknown; output?: unknown }
type Evidence = { id: string; title?: string; text: string; source: string; verified?: boolean }
type Draft = { title: string; summary: string; category: string; owner: string; evidence_ids: string[] }
type Run = { id: string; feedback_id: string; status: string; snapshot: { mode: string; model: string; input: { text: string; version: string }; runtime_version: string }; trace: Trace[]; result: { summary?: string; category?: string; owner?: string; draft?: Draft; evidence?: Evidence[] }; error_message?: string; token_used: number; duration_ms: number }
type Ticket = { id: string; run_id: string; draft: Draft }
type Capability = { real_model_configured: boolean; knowledge: Evidence[] }
type EvalCase = { case_id: string; safe_completion: boolean; tool_complete: boolean | null; duplicate_retrieved?: boolean | null; tokens: number; error?: string }
type Evaluation = { mode: string; sample_count: number; limitations: string; reports: { strategy: string; metrics: Record<string, number>; total_tokens: number; duration_ms: number; cases: EvalCase[] }[] }
const labels: Record<string, string> = { pending: '等待执行', running: '执行中', awaiting_confirmation: '待人工确认', needs_information: '需要补充信息', confirmed: '已确认', failed: '执行失败', bug: '研发缺陷', balance: '平衡性', experience: '体验问题', unknown: '待判断', engineering: '研发', game_design: '策划', operations: '运营', manual_review: '人工复核', rule: '规则基线', single_llm: '单次响应', agent: '工具调用 Agent' }

export default function AgentWorkspace() {
  const [feedbacks, setFeedbacks] = useState<Feedback[]>([])
  const [runs, setRuns] = useState<Run[]>([])
  const [tickets, setTickets] = useState<Ticket[]>([])
  const [capability, setCapability] = useState<Capability | null>(null)
  const [selectedId, setSelectedId] = useState('')
  const [text, setText] = useState('2.4 更新后火球技能伤害异常，请核实倍率。')
  const [version, setVersion] = useState('2.4')
  const [mode, setMode] = useState('mock')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null)
  const [tab, setTab] = useState<'workspace' | 'evaluation'>('workspace')
  const reload = useCallback(async () => {
    const [f, r, t, c] = await Promise.all([api('/agent/feedbacks'), api('/agent/runs'), api('/agent/tickets'), api('/agent/capabilities')])
    setFeedbacks(f); setRuns(r); setTickets(t); setCapability(c)
  }, [])
  useEffect(() => { reload().catch(e => setError(String(e))) }, [reload])
  const running = runs.some(r => r.status === 'pending' || r.status === 'running')
  useEffect(() => {
    if (!running) return
    let active = true
    const timer = window.setInterval(() => {
      api('/agent/runs').then((data: Run[]) => { if (active) setRuns(data) }).catch(e => { if (active) setError(String(e)) })
    }, 1500)
    return () => { active = false; window.clearInterval(timer) }
  }, [running])
  const selected = runs.find(r => r.id === selectedId) ?? runs[0]
  const submit = async (feedbackId?: string) => {
    setBusy(true); setError(''); setNotice('')
    try {
      const feedback = feedbackId ? { id: feedbackId } : await api('/agent/feedbacks', { method: 'POST', body: JSON.stringify({ text, version }) })
      const run = await api('/agent/runs', { method: 'POST', body: JSON.stringify({ feedback_id: feedback.id, mode }) })
      setSelectedId(run.id); await reload()
    } catch (e) { setError(String(e)); await reload().catch(() => {}) }
    finally { setBusy(false) }
  }
  const confirm = async () => {
    if (!selected) return
    setBusy(true); setError('')
    try {
      const ticket = await api(`/agent/runs/${selected.id}/confirm`, { method: 'POST' })
      setNotice(`已保存本地工单 ${ticket.id.slice(0, 8)}，未发送到外部系统。`); await reload()
    } catch (e) { setError(String(e)) }
    finally { setBusy(false) }
  }
  const evaluate = async () => {
    setBusy(true); setError('')
    try { setEvaluation(await api('/agent/evaluation')) } catch (e) { setError(String(e)) }
    finally { setBusy(false) }
  }
  return <div className="agent-workspace">
    <div className="agent-intro"><div><h2>反馈处理 Agent</h2><p>查询版本资料与相似反馈，生成可追溯的处理草稿。</p></div><div className="agent-tabs"><button className={tab === 'workspace' ? 'active' : ''} onClick={() => setTab('workspace')}>工作台</button><button className={tab === 'evaluation' ? 'active' : ''} onClick={() => setTab('evaluation')}>效果评估</button></div></div>
    <div className="agent-banner">资料来自内置示例，采用关键词检索。Mock 模式模拟工具选择，不代表真实模型效果。工单经人工确认后保存在本项目中。</div>
    {error && <p className="agent-error" role="alert">{error}</p>}{notice && <p className="agent-notice" role="status">{notice}</p>}
    {tab === 'workspace' ? <>
      <div className="agent-grid"><section className="agent-card"><h3>提交反馈</h3><form onSubmit={e => { e.preventDefault(); void submit() }}>
        <label>问题描述<textarea required minLength={3} maxLength={4000} value={text} onChange={e => setText(e.target.value)} rows={5}/></label>
        <div className="agent-form-row"><label>版本<input required maxLength={80} value={version} onChange={e => setVersion(e.target.value)}/></label><label>运行模式<select value={mode} onChange={e => setMode(e.target.value)}><option value="mock">Mock 演示</option><option value="openai" disabled={!capability?.real_model_configured}>真实模型{!capability?.real_model_configured ? '（未配置）' : ''}</option></select></label></div>
        <button className="primary" disabled={busy || !text.trim() || !version.trim()}>{busy ? '处理中…' : '提交并分析'}</button>
      </form><details><summary>查看示例知识来源</summary>{capability?.knowledge.map(n => <article className="agent-evidence" key={n.id}><b>{n.title}</b><p>{n.text}</p><code>{n.source}</code></article>)}</details>
      <details><summary>历史反馈（{feedbacks.length}）</summary>{feedbacks.map(f => <div className="agent-history" key={f.id}><span>{f.version} · {f.text}</span><button disabled={busy} onClick={() => void submit(f.id)}>重新分析</button></div>)}</details></section>
      <section className="agent-card"><h3>运行记录</h3>{!runs.length && <p className="agent-muted">提交反馈后可查看运行步骤。</p>}<div className="agent-run-list">{runs.map(r => <button className={selected?.id === r.id ? 'selected' : ''} key={r.id} onClick={() => setSelectedId(r.id)}><span>{r.snapshot.input.text}</span><small>{r.snapshot.mode === 'mock' ? 'Mock' : '真实模型'} · {labels[r.status] ?? r.status} · {r.id.slice(0, 8)}</small></button>)}</div></section></div>
      {selected && <section className="agent-card agent-detail"><div className="agent-detail-title"><h3>{labels[selected.status] ?? selected.status}</h3><span>{selected.snapshot.model} · {selected.duration_ms} ms · {selected.token_used} tokens{selected.snapshot.mode === 'mock' ? '（无模型调用）' : ''}</span></div>
        <p>{selected.result.summary || '运行结束后显示处理建议。'}</p>{selected.error_message && <p className="agent-error">{selected.error_message}</p>}
        {selected.result.category && <p className="agent-muted">分类：{labels[selected.result.category]} · 处理方：{labels[selected.result.owner ?? '']}</p>}
        {selected.result.draft && <div className="agent-draft"><h4>待确认工单草稿</h4><b>{selected.result.draft.title}</b><p>{selected.result.draft.summary}</p><p>证据：{selected.result.draft.evidence_ids.join('、')}</p><button className="primary" disabled={busy || selected.status !== 'awaiting_confirmation'} onClick={() => void confirm()}>{selected.status === 'confirmed' ? '已确认保存' : '人工确认并保存工单'}</button></div>}
        <h4>检索证据</h4>{selected.result.evidence?.length ? selected.result.evidence.map(n => <article className="agent-evidence" key={n.id}><b>{n.title ?? '相似反馈（未经核实）'}</b><p>{n.text}</p><code>{n.id} · {n.source}</code></article>) : <p className="agent-muted">暂无检索证据。</p>}
        <h4>执行轨迹</h4>{selected.trace.map((t, i) => <details className="agent-trace" key={i}><summary>步骤 {t.step} · {t.kind === 'tool' ? t.name : '模型响应'} · {t.status} · {t.duration_ms ?? 0} ms{t.tokens ? ` · ${t.tokens} tokens` : ''}</summary><pre>{JSON.stringify(t, null, 2)}</pre></details>)}
        <details><summary>查看固定运行快照</summary><pre>{JSON.stringify(selected.snapshot, null, 2)}</pre></details>
      </section>}
      <section className="agent-card"><h3>已确认工单（{tickets.length}）</h3>{tickets.length ? tickets.map(t => <article className="agent-evidence" key={t.id}><b>{t.draft.title}</b><p>{labels[t.draft.owner]} · {t.id.slice(0, 8)} · 运行 {t.run_id.slice(0, 8)}</p></article>) : <p className="agent-muted">分析不会自动创建工单。</p>}</section>
    </> : <section className="agent-card"><h3>离线评估</h3><p>对规则基线、单次响应和工具调用 Agent 使用同一组人工标注的合成样本。</p><button className="primary" disabled={busy} onClick={() => void evaluate()}>{busy ? '评估中…' : '运行 Mock 评估'}</button>
      {evaluation && <><p className="agent-muted">{evaluation.sample_count} 个样本 · {evaluation.mode} · Mock Token 为 0；未计算费用。基线没有检索，单次 Mock 响应复用规则分类器。此比较不能证明真实模型优于基线。</p><div className="agent-table-wrap"><table><thead><tr><th>方案</th><th>分类正确率</th><th>路由正确率</th><th>安全完成率</th><th>证据检查通过率</th><th>耗时</th></tr></thead><tbody>{evaluation.reports.map(r => <tr key={r.strategy}><td>{labels[r.strategy]}</td><td>{r.metrics.category_correct}%</td><td>{r.metrics.owner_correct}%</td><td>{r.metrics.safe_completion}%</td><td>{r.metrics.evidence_correct}%</td><td>{r.duration_ms} ms</td></tr>)}</tbody></table></div><p className="agent-muted">安全完成要求：证据不足时请求补充信息；证据充分时生成带来源的待确认草稿。证据检查只校验来源 ID，不验证语义蕴含。</p>{evaluation.reports.map(r => <details key={r.strategy}><summary>{labels[r.strategy]}：逐项结果</summary><pre>{JSON.stringify(r.cases, null, 2)}</pre></details>)}</>}
    </section>}
  </div>
}
