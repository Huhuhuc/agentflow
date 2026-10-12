import { useCallback, useEffect, useMemo, useState } from 'react'
import { Background, Controls, Handle, Position, ReactFlow, type Edge, type Node, type NodeProps } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { Activity, BarChart3, Blocks, Bot, CheckCircle2, ChevronRight, CirclePlay, Clock3, FileStack, LayoutDashboard, LogOut, Search, Settings, Sparkles, Workflow as WorkflowIcon, Zap } from 'lucide-react'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, bootstrapSession, BASE } from './api'
import './App.css'
import './FlowNode.css'
import AgentWorkspace from './AgentWorkspace'
import Login from './Login'
import BusinessWorkspace from './ServiceWorkspace'

type View = 'dashboard' | 'workflows' | 'builder' | 'templates' | 'executions' | 'analytics' | 'agent' | 'business'
type Workflow = { id: string; name: string; description: string; status: string; graph: { nodes: Node[]; edges: Edge[] }; updated_at: string }
type ExecutionLog = { id: string; node_id: string; node_name: string; node_type: string; status: string; duration_ms: number; token_used: number; output_data: Record<string, unknown> }
type Execution = { id: string; workflow_id: string; status: string; duration_ms: number; token_used: number; cost: number; created_at: string; logs: ExecutionLog[] }
type Template = { id: string; name: string; description: string; category: string; use_count: number }

const nav = [
  { id: 'business', label: '企业服务 Agent', icon: Bot },
  { id: 'agent', label: '反馈处理 Agent', icon: Bot },
  { id: 'dashboard', label: '总览看板', icon: LayoutDashboard },
  { id: 'workflows', label: '工作流', icon: WorkflowIcon },
  { id: 'builder', label: '工作流构建器', icon: Blocks },
  { id: 'templates', label: '模板市场', icon: FileStack },
  { id: 'executions', label: '运行监控', icon: Activity },
  { id: 'analytics', label: '数据分析', icon: BarChart3 },
] as const


function WorkflowNode({ data, type }: NodeProps) {
  return <div className={`flow-node ${type}`}><Handle type="target" position={Position.Left}/><span>{type === 'agent' ? <Bot size={15}/> : <Zap size={15}/>}</span><div><b>{String(data.label ?? type)}</b><small>{type}</small></div><Handle type="source" position={Position.Right}/></div>
}

const nodeTypes = { trigger: WorkflowNode, agent: WorkflowNode, condition: WorkflowNode, http: WorkflowNode, notification: WorkflowNode, output: WorkflowNode }

function Metric({ label, value, foot, tone = 'green' }: { label: string; value: string; foot: string; tone?: 'green' | 'purple' }) {
  return <section className="metric"><p>{label}</p><strong>{value}</strong><small className={tone}>{foot}</small></section>
}

function Sidebar({ view, setView }: { view: View; setView: (view: View) => void }) {
  return <aside className="sidebar">
    <div className="brand"><div className="brand-mark">A</div><div><b>AgentFlow</b><span>AI 工作流编排平台</span></div></div>
    <div className="nav-caption">工作台</div>
    <nav>{nav.map(item => <button key={item.id} className={view === item.id ? 'active' : ''} onClick={() => setView(item.id)}><item.icon size={18}/><span>{item.label}</span></button>)}</nav>
    <div className="nav-caption system">系统</div>
    <button className="settings"><Settings size={18}/>系统设置</button>
    <div className="profile"><div className="avatar">胡</div><div><b>胡宸凡</b><span>团队管理员</span></div><LogOut size={17}/></div>
  </aside>
}

function Dashboard({ workflows, executions, analytics, setView }: { workflows: Workflow[]; executions: Execution[]; analytics: any; setView: (v: View) => void }) {
  const trend = Array.from({ length: 14 }, (_, index) => {
    const date = new Date(); date.setDate(date.getDate() - 13 + index)
    return { day: `${date.getMonth() + 1}/${date.getDate()}`, value: executions.filter(e => new Date(e.created_at).toDateString() === date.toDateString()).length }
  })
  return <>
    <div className="metrics">
      <Metric label="活跃工作流" value={String(analytics.active_workflows ?? workflows.length)} foot="当前租户工作流" />
      <Metric label="累计执行次数" value={String(analytics.executions ?? executions.length)} foot="Mock 模式可完整演示" />
      <Metric label="执行成功率" value={`${analytics.success_rate ?? 100}%`} foot="全链路可追踪" />
      <Metric label="Token 消耗" value={(analytics.token_used ?? 0).toLocaleString()} foot={`旧工作流演示估算 ${analytics.cost ?? 0}`} tone="purple" />
    </div>
    <section className="panel workflow-panel"><div className="section-title"><div><h2>工作流列表</h2><p>按最近更新时间排序</p></div><button className="text-action" onClick={() => setView('builder')}>新建工作流 <ChevronRight size={15}/></button></div>
      <div className="workflow-list">{workflows.map((flow, i) => <button key={flow.id} className="workflow-row" onClick={() => setView('builder')}><span className={`row-accent c${i % 4}`}/><span className="row-icon"><Bot size={18}/></span><span className="row-copy"><b>{flow.name}</b><small>{flow.description}</small></span><span className={`status ${flow.status}`}>{flow.status === 'published' ? '已发布' : '草稿'}</span><ChevronRight size={17}/></button>)}</div>
    </section>
    <div className="two-col"><section className="panel chart-panel"><div className="section-title"><div><h2>执行趋势</h2><p>近 14 天工作流执行量</p></div></div><ResponsiveContainer width="100%" height={220}><AreaChart data={trend}><defs><linearGradient id="fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#6758d9" stopOpacity={0.28}/><stop offset="100%" stopColor="#6758d9" stopOpacity={0}/></linearGradient></defs><CartesianGrid stroke="#edf0f4" vertical={false}/><XAxis dataKey="day" tickLine={false} axisLine={false} tick={{fill:'#8b909a',fontSize:11}}/><YAxis hide/><Tooltip/><Area type="monotone" dataKey="value" stroke="#6758d9" strokeWidth={2.5} fill="url(#fill)"/></AreaChart></ResponsiveContainer></section>
      <section className="panel health"><div className="section-title"><div><h2>运行健康度</h2><p>最近执行状态</p></div></div><div className="health-score"><span>{analytics.success_rate ?? 0}%</span><small>执行成功率</small></div><div className="health-row"><CheckCircle2 size={18}/>成功执行<b>{executions.filter(x=>x.status==='success').length}</b></div><div className="health-row"><Clock3 size={18}/>平均耗时<b>{executions.length ? Math.round(executions.reduce((a,b)=>a+b.duration_ms,0)/executions.length) : 0} ms</b></div></section></div>
  </>
}

function Builder({ workflow, onSaved, executions, setView }: { workflow?: Workflow; onSaved: () => void; executions: Execution[]; setView: (v: View) => void }) {
  const [nodes, setNodes] = useState<Node[]>(workflow?.graph.nodes ?? [])
  const [edges, setEdges] = useState<Edge[]>(workflow?.graph.edges ?? [])
  const [selected, setSelected] = useState<Node | null>(null)
  const [message, setMessage] = useState('')
  const [liveNodes, setLiveNodes] = useState<Record<string, { node_name: string; node_type: string; status: string; token_used: number }>>({})
  useEffect(() => { if (workflow) { setNodes(workflow.graph.nodes); setEdges(workflow.graph.edges) } }, [workflow])
  const save = async () => { if (!workflow) return; await api(`/workflows/${workflow.id}`, { method:'PUT', body: JSON.stringify({ graph:{nodes,edges} }) }); setMessage('已保存草稿'); onSaved() }
  const publish = async () => { if (!workflow) return; await save(); const result = await api(`/workflows/${workflow.id}/validate`, {method:'POST'}); if (!result.valid) return setMessage(result.errors.join('；')); await api(`/workflows/${workflow.id}/publish`, {method:'POST'}); setMessage('已发布新版本'); onSaved() }
  const run = async () => {
    if (!workflow) return
    setMessage('正在执行…')
    setLiveNodes({})
    const exec = await api(`/workflows/${workflow.id}/execute`, {method:'POST', body: JSON.stringify({input_data:{ticket_id:'T-20260715-01',message:'请问企业版如何配置知识库？'}})})
    const token = localStorage.getItem('agentflow_token') ?? ''
    const es = new EventSource(`${BASE}/executions/${exec.id}/events?token=${token}`)
    es.addEventListener('node', (e: MessageEvent) => { const d = JSON.parse(e.data); setLiveNodes(prev => ({...prev, [d.node_id]: d})) })
    es.onmessage = (e: MessageEvent) => { const d = JSON.parse(e.data); if (d.status) setMessage(`执行中：${d.status} · ${d.token_used} tokens`) }
    es.addEventListener('done', () => { es.close(); setMessage('执行完成，可在运行监控查看日志'); onSaved() })
    es.onerror = () => es.close()
  }
  return <div className="builder-shell"><div className="builder-bar"><div><h2>{workflow?.name ?? '工作流构建器'}</h2><span>{message || '编辑后请保存草稿'}</span></div><div className="builder-actions"><button onClick={save}>保存</button><button onClick={publish}>发布</button><button className="primary" onClick={run}><CirclePlay size={16}/>试运行</button></div></div>
    <div className="builder-body"><aside className="node-library"><h3>节点库</h3>{['trigger','agent','condition','http','notification','output'].map(type=><div key={type}><Zap size={16}/><span>{type}</span></div>)}</aside><main className="canvas"><ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} onNodesChange={(changes:any)=>setNodes(ns=>changes.reduce((acc:any,c:any)=>c.type==='position'?acc.map((n:any)=>n.id===c.id?{...n,position:c.position}:n):acc,ns))} onNodeClick={(_,node)=>setSelected(node)} fitView><Background color="#e3e6ed" gap={22}/><Controls/></ReactFlow></main><aside className="inspector"><h3>节点配置</h3>{selected ? <><label>名称<input value={String(selected.data.label ?? '')} onChange={e=>setNodes(ns=>ns.map(n=>n.id===selected.id?{...n,data:{...n.data,label:e.target.value}}:n))}/></label><label>类型<input value={selected.type ?? ''} disabled/></label><label>节点 ID<input value={selected.id} disabled/></label><p>配置修改会保存到工作流草稿，并在发布时生成不可变版本。</p></> : <div className="empty-inspector"><Blocks size={28}/><p>选择画布节点查看配置</p></div>}</aside></div>
    {Object.keys(liveNodes).length > 0 && <div className="live-progress"><b>实时进度</b>{Object.values(liveNodes).map(n=><span key={n.node_name} className={`live-node ${n.status}`}><CheckCircle2 size={12}/>{n.node_name} · {n.status}{n.token_used ? ` · ${n.token_used}t` : ''}</span>)}</div>}
    {executions[0] && <div className="last-run"><CheckCircle2 size={16}/>最近执行 {executions[0].status} · {executions[0].duration_ms} ms · {executions[0].token_used} tokens <button onClick={()=>setView('executions')}>查看日志</button></div>}</div>
}

function Templates({ templates }: { templates: Template[] }) { return <section className="page-panel"><div className="page-intro"><h2>模板市场</h2><p>从经过验证的企业场景快速创建工作流。</p></div><div className="template-grid">{templates.map((item,i)=><article key={item.id} className="template-card"><div className={`template-icon t${i%3}`}><Sparkles size={20}/></div><h3>{item.name}</h3><p>{item.description}</p><div><span>{item.category}</span><b>{item.use_count.toLocaleString()} 次使用</b></div><button>使用模板</button></article>)}</div></section> }

function Executions({ executions }: { executions: Execution[] }) { return <section className="page-panel"><div className="page-intro"><h2>运行监控</h2><p>查看每次执行的节点日志、延迟与成本。</p></div><div className="exec-table"><div className="table-head"><span>状态</span><span>执行 ID</span><span>耗时</span><span>Token</span><span>成本</span><span>时间</span></div>{executions.map(item=><div className="table-row" key={item.id}><span className={`status ${item.status}`}>{item.status}</span><code>{item.id.slice(0,8)}</code><span>{item.duration_ms} ms</span><span>{item.token_used}</span><span>{item.cost}（演示估算）</span><span>{new Date(item.created_at).toLocaleString()}</span><div className="log-strip">{item.logs.map(log=><span key={log.id}><CheckCircle2 size={13}/>{log.node_name}</span>)}</div></div>)}{!executions.length && <div className="empty-state">尚无执行记录，请在工作流构建器中点击“试运行”。</div>}</div></section> }

function App() {
  const [view, setView] = useState<View>('business')
  const [workflows, setWorkflows] = useState<Workflow[]>([])
  const [executions, setExecutions] = useState<Execution[]>([])
  const [templates, setTemplates] = useState<Template[]>([])
  const [analytics, setAnalytics] = useState<any>({})
  const [ready, setReady] = useState(false)
  const [loginRequired, setLoginRequired] = useState(false)
  const load = useCallback(async () => { await bootstrapSession(); const [w,e,t,a] = await Promise.all([api('/workflows'),api('/executions'),api('/templates'),api('/analytics/overview')]); setWorkflows(w); setExecutions(e); setTemplates(t); setAnalytics(a); setLoginRequired(false); setReady(true) }, [])
  useEffect(() => { load().catch(()=>{setLoginRequired(true);setReady(true)}) }, [load])
  const title = useMemo(()=>nav.find(x=>x.id===view)?.label ?? 'AgentFlow',[view])
  if (loginRequired) return <Login onSuccess={async()=>{await load();setLoginRequired(false)}}/>
  return <div className="app"><Sidebar view={view} setView={setView}/><main className="main"><header><div><h1>{title}</h1><span>本地演示</span></div><button aria-label="搜索"><Search size={18}/></button></header><div className="content">{!ready ? <div className="loading">正在连接 AgentFlow 服务…</div> : view==='business' ? <BusinessWorkspace/> : view==='agent' ? <AgentWorkspace/> : view==='dashboard' ? <Dashboard workflows={workflows} executions={executions} analytics={analytics} setView={setView}/> : view==='builder' ? <Builder workflow={workflows[0]} onSaved={load} executions={executions} setView={setView}/> : view==='templates' ? <Templates templates={templates}/> : view==='executions' ? <Executions executions={executions}/> : view==='analytics' ? <Dashboard workflows={workflows} executions={executions} analytics={analytics} setView={setView}/> : <section className="page-panel"><div className="page-intro"><h2>工作流</h2><p>管理草稿、已发布版本和执行入口。</p></div><div className="workflow-list">{workflows.map(flow=><button key={flow.id} className="workflow-row" onClick={()=>setView('builder')}><span className="row-icon"><WorkflowIcon size={18}/></span><span className="row-copy"><b>{flow.name}</b><small>{flow.description}</small></span><span className={`status ${flow.status}`}>{flow.status}</span></button>)}</div></section>}</div></main></div>
}

export default App
