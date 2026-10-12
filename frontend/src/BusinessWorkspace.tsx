import { useEffect, useState } from 'react'
import { api } from './api'
import './AgentWorkspace.css'
import BusinessEvaluation from './BusinessEvaluation'

type Run = { id: string; status: string; snapshot: { mode: string; input: { text: string } }; result: { summary?: string; draft?: {title: string; summary: string}; evidence?: {id: string; title: string; text: string; source: string}[] }; trace: unknown[]; token_used: number; duration_ms: number; error_message?: string }
const labels: Record<string,string> = {pending:'等待执行', running:'运行中', completed:'已完成', awaiting_confirmation:'等待确认', confirmed:'已创建工单', needs_information:'需要补充信息', failed:'失败', cancelled:'已取消', rejected:'已拒绝'}
export default function BusinessWorkspace() {
  const [runs,setRuns]=useState<Run[]>([])
  const [text,setText]=useState('订单 A102 为什么无法退款？请生成申诉工单。')
  const [mode,setMode]=useState('mock')
  const [error,setError]=useState('')
  const [busy,setBusy]=useState(false)
  const [selected,setSelected]=useState('')
  const [real,setReal]=useState(false)
  const load=async()=>setRuns(await api('/business/runs'))
  useEffect(()=>{ void load().catch(e=>setError(String(e))); void api('/business/catalogue').then(c=>setReal(c.real_model_configured)).catch(e=>setError(String(e))) },[])
  const active=runs.some(r=>['pending','running'].includes(r.status))
  useEffect(()=>{if(!active)return; const timer=setInterval(()=>void load().catch(e=>setError(String(e))),1000); return ()=>clearInterval(timer)},[active])
  const run=runs.find(r=>r.id===selected)??runs[0]
  const act=async(action?:string)=>{setBusy(true);setError('');try{const result=await api(action?`/business/runs/${run.id}/${action}`:'/business/runs',{method:'POST',...(!action?{body:JSON.stringify({text,mode})}:{})});if(!action)setSelected(result.id);await load()}catch(e){setError(String(e))}finally{setBusy(false)}}
  return <div className="agent-workspace"><div className="agent-intro"><div><h2>企业服务 Agent</h2><p>查询订单与规则，解释处理依据，确认后创建服务工单。</p></div></div>
    <div className="agent-banner">使用模拟订单 A101（签收3天未使用）、A102（签收12天已使用）、A103（配送逾期）。规则采用关键词检索。Mock 为确定性演示，真实模型需配置。工单保存在本平台。</div>
    {error&&<p role="alert" className="agent-error">{error}</p>}
    <div className="agent-grid"><section className="agent-card"><h3>提交任务</h3><form onSubmit={e=>{e.preventDefault();void act()}}><label>任务描述<textarea rows={5} minLength={3} maxLength={4000} required value={text} onChange={e=>setText(e.target.value)}/></label><label>执行方式<select value={mode} onChange={e=>setMode(e.target.value)}><option value="mock">Mock 演示</option><option value="openai" disabled={!real}>真实模型{!real?'（未配置）':''}</option></select></label><button className="primary" disabled={busy}>执行任务</button></form></section>
    <section className="agent-card"><h3>运行记录</h3><div className="agent-run-list">{runs.map(r=><button key={r.id} className={run?.id===r.id?'selected':''} onClick={()=>setSelected(r.id)}><span>{r.snapshot.input.text}</span><small>{labels[r.status]} · {r.snapshot.mode}</small></button>)}</div></section></div>
    {run&&<section className="agent-card"><h3>{labels[run.status]}</h3><p>{run.result.summary}</p><p>{run.duration_ms} ms · {run.token_used} tokens{run.snapshot.mode==='mock'?'（无模型调用）':''}</p>{run.error_message&&<p className="agent-error">{run.error_message}</p>}
    {run.result.draft&&<div className="agent-draft"><h4>{run.result.draft.title}</h4><p>{run.result.draft.summary}</p></div>}
    {run.status==='awaiting_confirmation'&&<><button disabled={busy} className="primary" onClick={()=>void act('confirm')}>确认并创建工单</button><button disabled={busy} onClick={()=>void act('reject')}>拒绝草稿</button></>}
    {['pending','running','awaiting_confirmation'].includes(run.status)&&<button disabled={busy} onClick={()=>void act('cancel')}>取消任务</button>}
    {run.status==='failed'&&<button disabled={busy} onClick={()=>void act('resume')}>从检查点重试</button>}
    <h4>引用依据</h4>{run.result.evidence?.map(e=><article className="agent-evidence" key={e.id}><b>{e.title}</b><p>{e.text}</p><code>{e.source}</code></article>)}
    <h4>执行轨迹</h4>{run.trace.map((t,i)=><details className="agent-trace" key={i}><summary>事件 {i+1}</summary><pre>{JSON.stringify(t,null,2)}</pre></details>)}</section>}
    <BusinessEvaluation />
  </div>
}
