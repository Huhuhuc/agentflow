import { useEffect, useRef, useState } from 'react'
import { api } from './api'
import BusinessEvaluation from './BusinessEvaluation'
import ServiceExperiments from './ServiceExperiments'
import './AgentWorkspace.css'
import './ServiceWorkspace.css'

type Policy = { id: string; slug: string; title: string; text: string; version: number; topic: string; active: boolean; effective_from: string }
type Catalogue = { orders: Record<string, unknown>[]; policies: Policy[]; real_model_configured: boolean; role: string; execution_mode: string }
type Brief = { id: string; title: string; status: string; mode: string }
type Task = Brief & { revision: number; conversation_id: string; context: unknown; messages: {sequence: number; text: string; answer: string; status: string}[]; audit: unknown[];
  run: { id: string; status: string; trace: unknown[]; error_message?: string; duration_ms: number; token_used: number; result: {draft?: {title: string; summary: string}; evidence?: {id: string; title: string; text: string; source: string}[]} };
  ticket: { id: string; status: string; note: string; revision: number } | null }
const labels: Record<string, string> = { pending: '排队中', running: '执行中', awaiting_input: '等待补充', needs_information: '等待补充', completed: '已回答', awaiting_confirmation: '待审核', confirmed: '已建工单', rejected: '已拒绝', cancelled: '已取消', failed: '执行失败', open: '待处理', in_progress: '处理中', resolved: '已解决' }
const csvExample = 'id,status,amount,days_since_delivery,used,overdue\nA201,delivered,199,3,false,\nA202,shipping,89,,,true'

export default function ServiceWorkspace() {
  const [tab, setTab] = useState('tasks')
  const [items, setItems] = useState<Brief[]>([])
  const [task, setTask] = useState<Task | null>(null)
  const [catalogue, setCatalogue] = useState<Catalogue | null>(null)
  const [text, setText] = useState('我要申请退款')
  const [reply, setReply] = useState('')
  const [mode, setMode] = useState('mock')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [title, setTitle] = useState('')
  const [summary, setSummary] = useState('')
  const [note, setNote] = useState('')
  const [csv, setCSV] = useState(csvExample)
  const [slug, setSlug] = useState('refund')
  const [policyTitle, setPolicyTitle] = useState('退款规则')
  const [body, setBody] = useState('')
  const [topic, setTopic] = useState('refund')
  const [effective, setEffective] = useState('')
  const requestKeys = useRef(new Map<string, string>())
  const selected = useRef('')
  const keyFor = (signature: string) => {
    let key = requestKeys.current.get(signature)
    if (!key) { key = crypto.randomUUID(); requestKeys.current.set(signature, key) }
    return key
  }
  const refresh = async (id = selected.current) => {
    const rows: Brief[] = await api('/service/tasks'); setItems(rows)
    const target = id || rows[0]?.id
    if (target) { const value: Task = await api('/service/tasks/' + target); selected.current = target; setTask(value); localStorage.setItem('service_selected_task', target) }
    setCatalogue(await api('/service/catalogue'))
  }
  useEffect(() => { void (async () => {
    const rows: Brief[] = await api('/service/tasks')
    const saved = localStorage.getItem('service_selected_task')
    await refresh(rows.find(r => r.id === saved)?.id ?? rows[0]?.id ?? '')
  })().catch(e => setError(String(e))) }, [])
  const active = items.some(i => ['running', 'pending'].includes(i.status)) || !!task && ['running', 'pending'].includes(task.status)
  useEffect(() => { if (!active) return; const timer = setInterval(() => void refresh().catch(e => setError(String(e))), 1500); return () => clearInterval(timer) }, [active])
  useEffect(() => { setTitle(task?.run.result.draft?.title ?? ''); setSummary(task?.run.result.draft?.summary ?? ''); setNote(task?.ticket?.note ?? '') }, [task?.id, task?.revision, task?.ticket?.revision, task?.status])
  const perform = async (job: () => Promise<void>) => { setBusy(true); setError(''); try { await job() } catch (e) { setError(String(e)); await refresh().catch(() => {}) } finally { setBusy(false) } }
  const taskAction = (action: string, payload: object = {}, method = 'POST') => perform(async () => {
    if (!task) return
    await api('/service/tasks/' + task.id + '/' + action, {method, body: JSON.stringify({revision: task.revision, ...payload})}); await refresh(task.id)
  })
  const isStaff = catalogue && ['admin', 'staff'].includes(catalogue.role)
  const canReply = task && !['running', 'pending', 'confirmed', 'cancelled'].includes(task.status)
  return <div className="agent-workspace service-workspace">
    <div className="agent-intro"><div><h2>企业售后工作台</h2><p>补充资料、核对政策、审核草稿，在同一会话里完成工单处理。</p></div><span className="service-chip">{catalogue?.execution_mode === 'celery' ? '独立 Worker' : '本地执行'}</span></div>
    <nav className="service-tabs" aria-label="售后工作区">{[['tasks','会话与工单'],['catalogue','订单与政策'],['evaluation','评测与复核']].map(([id,label]) => <button key={id} aria-pressed={tab === id} onClick={() => setTab(id)}>{label}</button>)}</nav>
    {error && <p className="agent-error" role="alert">{error}</p>}
    {catalogue?.orders.length === 0 && <div className="agent-banner">当前租户还没有业务数据。{isStaff && <button disabled={busy} onClick={() => void perform(async () => { await api('/service/catalogue/seed', {method:'POST'}); await refresh() })}>加载明确标注的演示数据</button>}也可以在「订单与政策」导入自己的测试资料。</div>}
    {tab === 'tasks' && <>
      <div className="agent-grid"><section className="agent-card"><h3>发起新任务</h3><form onSubmit={e => {e.preventDefault(); void perform(async () => {
        const signature = 'start:' + mode + ':' + text
        const created: Task = await api('/service/tasks', {method:'POST', body: JSON.stringify({text, mode, request_key:keyFor(signature)})})
        requestKeys.current.delete(signature); await refresh(created.id)
      })}}><label>任务描述<textarea required maxLength={4000} rows={3} value={text} onChange={e => setText(e.target.value)} /></label><label>执行方式<select value={mode} onChange={e => setMode(e.target.value)}><option value="mock">Mock · 流程验证</option><option value="openai" disabled={!catalogue?.real_model_configured}>真实模型{!catalogue?.real_model_configured && '（未配置）'}</option></select></label><button className="primary" disabled={busy}>新建会话</button></form><p className="service-muted">Mock 汇集订单事实与政策原文，不作模型能力证明。工单保存在本平台。</p></section>
      <section className="agent-card"><h3>最近任务</h3><div className="agent-run-list">{items.map(item => <button key={item.id} disabled={busy} className={task?.id === item.id ? 'selected' : ''} onClick={() => void perform(() => refresh(item.id))}><span>{item.title}</span><small>{labels[item.status] ?? item.status} · {item.mode}</small></button>)}</div></section></div>
      {task && <section className="agent-card"><h3>{task.title} <span className="service-chip">{labels[task.status]}</span></h3><p className="service-muted">会话 {task.conversation_id.slice(0,8)} · 任务版本 {task.revision}</p>
        <div className="service-messages">{task.messages.map(message => <article key={message.sequence}><p className="service-user"><b>你</b><br/>{message.text}</p><p className="service-assistant"><b>Agent</b><br/>{message.answer || labels[message.status]}</p></article>)}</div>
        {task.run.error_message && <p className="agent-error">{task.run.error_message}</p>}
        {canReply && <form onSubmit={e => {e.preventDefault(); void perform(async () => {
          const signature = 'reply:' + task.id + ':' + task.revision + ':' + reply
          await api('/service/tasks/' + task.id + '/messages', {method:'POST', body:JSON.stringify({text:reply, revision:task.revision, request_key:keyFor(signature)})})
          requestKeys.current.delete(signature); setReply(''); await refresh(task.id)
        })}}><label>继续补充信息<input required maxLength={4000} placeholder="例如：A102；或请生成工单，注明商品问题" value={reply} onChange={e => setReply(e.target.value)} /></label><button disabled={busy} className="primary">发送并继续处理</button><p className="service-muted">发送新消息会替代尚未确认的旧草稿，重新核对数据。</p></form>}
        {task.status === 'awaiting_confirmation' && task.run.result.draft && <div className="agent-draft"><h4>人工审核</h4><label>工单标题<input value={title} maxLength={150} onChange={e => setTitle(e.target.value)} disabled={!isStaff}/></label><label>处理说明<textarea rows={4} value={summary} maxLength={2000} onChange={e => setSummary(e.target.value)} disabled={!isStaff}/></label>
          {isStaff && <><button disabled={busy || title.trim().length < 3 || summary.trim().length < 3} onClick={() => void taskAction('draft', {title,summary}, 'PATCH')}>保存草稿修改</button><button className="primary" disabled={busy || title !== task.run.result.draft.title || summary !== task.run.result.draft.summary} onClick={() => void taskAction('confirm')}>确认并创建工单</button><button disabled={busy} onClick={() => void taskAction('reject')}>拒绝草稿</button></>}
          <p className="service-muted">修改后先保存。确认时再次校验订单与政策版本；依据已变化时需补充消息重新处理。</p></div>}
        {task.ticket && <div className="agent-draft"><h4>工单 {task.ticket.id.slice(0,8)} · {labels[task.ticket.status]}</h4><label>处理记录<textarea rows={2} maxLength={2000} value={note} onChange={e => setNote(e.target.value)} disabled={!isStaff}/></label>{isStaff && ['in_progress','resolved'].map(status => <button key={status} disabled={busy || status === 'resolved' && !note.trim()} onClick={() => void taskAction('ticket', {revision:task.ticket!.revision,status,note}, 'PATCH')}>{status === 'resolved' ? '记录解决结果' : '标记处理中'}</button>)}</div>}
        {task.status === 'failed' && <button disabled={busy} onClick={() => void taskAction('resume')}>从检查点重试</button>}
        {!['confirmed','cancelled'].includes(task.status) && <button disabled={busy} onClick={() => void taskAction('cancel')}>取消任务</button>}
        <details className="agent-trace"><summary>引用依据（当前运行快照）</summary>{task.run.result.evidence?.map(e => <article className="agent-evidence" key={e.id}><b>{e.title}</b><p>{e.text}</p><code>{e.source}</code></article>)}</details>
        <details className="agent-trace"><summary>执行轨迹 · {task.run.duration_ms} ms · {task.run.token_used} 已记录 tokens</summary><pre>{JSON.stringify(task.run.trace,null,2)}</pre></details>
        <details className="agent-trace"><summary>审核与操作记录</summary><pre>{JSON.stringify(task.audit,null,2)}</pre></details>
      </section>}
    </>}
    {tab === 'catalogue' && <>
      <div className="agent-grid"><section className="agent-card"><h3>订单 CSV 导入</h3><p>订单号采用 A 加三位数字；相同订单号更新当前租户的记录。</p><label>选择 CSV 文件<input type="file" accept=".csv,text/csv" disabled={!isStaff} onChange={e => {const file=e.target.files?.[0]; if(file) void perform(async () => {if(file.size>300000)throw new Error('文件超过300 KB');setCSV(await file.text())});e.target.value=''}}/></label><label>CSV 内容<textarea rows={7} value={csv} onChange={e => setCSV(e.target.value)} disabled={!isStaff}/></label><button disabled={busy || !isStaff} onClick={() => void perform(async () => {await api('/service/orders/import',{method:'POST',body:JSON.stringify({text:csv})});await refresh()})}>校验并导入</button><details><summary>当前订单 {catalogue?.orders.length ?? 0} 条</summary><pre>{JSON.stringify(catalogue?.orders,null,2)}</pre></details></section>
      <section className="agent-card"><h3>发布政策版本</h3><form onSubmit={e => {e.preventDefault();void perform(async () => {await api('/service/policies',{method:'POST',body:JSON.stringify({slug,title:policyTitle,text:body,topic,order_status:topic==='refund'?'delivered':'shipping',effective_from:effective?new Date(effective).toISOString():null})});await refresh()})}}>
        <label>文档标识<input required pattern="[a-z][a-z0-9-]{1,79}" value={slug} onChange={e => setSlug(e.target.value)} disabled={!isStaff}/></label><label>标题<input required minLength={2} maxLength={150} value={policyTitle} onChange={e => setPolicyTitle(e.target.value)} disabled={!isStaff}/></label><label>适用范围<select value={topic} onChange={e => setTopic(e.target.value)} disabled={!isStaff}><option value="refund">退款 · 已签收订单</option><option value="delivery">配送 · 运输中订单</option></select></label><label>生效时间（留空立即生效）<input type="datetime-local" value={effective} onChange={e=>setEffective(e.target.value)} disabled={!isStaff}/></label>
        <label>导入 Markdown / TXT<input type="file" accept=".md,.txt,text/plain" disabled={!isStaff} onChange={e => {const file=e.target.files?.[0];if(file)void perform(async()=>{if(file.size>90000)throw new Error('文件过大');setBody(await file.text())});e.target.value=''}}/></label><label>政策正文<textarea required minLength={10} maxLength={30000} rows={6} value={body} onChange={e => setBody(e.target.value)} disabled={!isStaff}/></label><button className="primary" disabled={busy || !isStaff}>发布新版本</button></form></section></div>
      <section className="agent-card"><h3>政策历史</h3>{catalogue?.policies.map(policy=><article className="agent-evidence" key={policy.id}><b>{policy.title} · {policy.slug} · v{policy.version}</b><p>{policy.active?'未下线':'已下线'} · {new Date(policy.effective_from).toLocaleString()} 生效</p><details><summary>查看原文</summary><pre>{policy.text}</pre></details>{isStaff&&<><button disabled={busy} onClick={()=>{setSlug(policy.slug);setPolicyTitle(policy.title);setBody(policy.text);setTopic(policy.topic);setEffective('')}}>基于此版编辑</button><button disabled={busy||!policy.active} onClick={()=>void perform(async()=>{await api('/service/policies/'+policy.id+'/withdraw',{method:'POST'});await refresh()})}>下线此版本</button></>}</article>)}</section>
    </>}
    {tab === 'evaluation' && <><ServiceExperiments/><details className="agent-card"><summary>导入已有离线报告</summary><BusinessEvaluation/></details></>}
  </div>
}
