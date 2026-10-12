import { useEffect, useState } from 'react'
import { api } from './api'
type Dataset = {id:string;name:string;cases:unknown[]}
type Row = {id:string;text:string;contract_pass:boolean;result:unknown;trace:unknown[];human_review:{rubric:string;factual_correct:boolean|null;notes:string}}
type Experiment = {id:string;status:string;revision:number;error?:string;config:{mode:string;split:string;repeats:number};report:{metrics?:Record<string,unknown>;progress?:unknown;rows?:Row[]}}
export default function ServiceExperiments(){
  const [datasets,setDatasets]=useState<Dataset[]>([])
  const [experiments,setExperiments]=useState<Experiment[]>([])
  const [selected,setSelected]=useState<Experiment|null>(null)
  const [dataset,setDataset]=useState('')
  const [split,setSplit]=useState('dev')
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  const [comparison,setComparison]=useState<unknown>(null)
  const [reviews,setReviews]=useState<Record<number,string>>({})
  const load=async(id?:string)=>{
    const ds:Dataset[]=await api('/service/datasets');setDatasets(ds);setDataset(current=>current||ds[0]?.id||'')
    const rows:Experiment[]=await api('/service/experiments');setExperiments(rows)
    if(id)setSelected(await api('/service/experiments/'+id))
  }
  useEffect(()=>{void load().catch(e=>setError(String(e)))},[])
  const active=experiments.some(e=>['pending','running'].includes(e.status))
  useEffect(()=>{if(!active)return;const timer=setInterval(()=>void load(selected?.id).catch(e=>setError(String(e))),1500);return()=>clearInterval(timer)},[active,selected?.id])
  const perform=async(job:()=>Promise<void>)=>{setBusy(true);setError('');try{await job()}catch(e){setError(String(e))}finally{setBusy(false)}}
  const saveScore=(index:number,correct:boolean|null)=>perform(async()=>{
    if(!selected)return
    const result:Experiment=await api('/service/experiments/'+selected.id+'/scores',{method:'PATCH',body:JSON.stringify({revision:selected.revision,row:index,correct,notes:reviews[index]??selected.report.rows?.[index].human_review.notes??''})})
    setSelected(result);await load()
  })
  const download=()=>{if(!selected)return;const url=URL.createObjectURL(new Blob([JSON.stringify(selected.report,null,2)],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download='experiment-'+selected.id+'.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
  return <section className="agent-card"><h3>数据库评测实验</h3><p>这里评测独立的合成工具运行器，不读取租户资料库。会话和审批流程由集成测试验证。实验结果、评分和版本信息在服务端保存。</p>
    {error&&<p role="alert" className="agent-error">{error}</p>}
    <button disabled={busy} onClick={()=>void perform(async()=>{await api('/service/datasets/seed',{method:'POST'});await load()})}>载入标准数据集</button>
    <label>数据集<select value={dataset} onChange={e=>setDataset(e.target.value)}>{datasets.map(d=><option key={d.id} value={d.id}>{d.name} · {d.cases.length}例</option>)}</select></label>
    <label>分组<select value={split} onChange={e=>setSplit(e.target.value)}><option value="dev">开发集</option><option value="test">测试集（冻结实现后使用）</option></select></label>
    <button className="primary" disabled={busy||!dataset} onClick={()=>void perform(async()=>{const e:Experiment=await api('/service/experiments',{method:'POST',body:JSON.stringify({dataset_id:dataset,mode:'mock',split,repeats:1})});await load(e.id)})}>运行 Mock 实验</button>
    <label>导入数据集 JSON<input type="file" accept=".json,application/json" disabled={busy} onChange={e=>{const file=e.target.files?.[0];if(file)void perform(async()=>{if(file.size>150000)throw new Error('文件过大');const input=JSON.parse(await file.text());await api('/service/datasets',{method:'POST',body:JSON.stringify(input)});await load()});e.target.value=''}}/></label>
    <p className="service-muted">导入格式为 name 和 cases；case字段与现有 business_cases.json 相同。每组最多12例；模型评测可经API显式创建，页面默认只运行Mock。</p>
    <div className="agent-run-list">{experiments.map(e=><button key={e.id} className={e.id===selected?.id?'selected':''} disabled={busy} onClick={()=>void perform(async()=>{setReviews({});setComparison(null);await load(e.id)})}><span>{e.id.slice(0,8)} · {e.config.mode} · {e.config.split}</span><small>{e.status}</small></button>)}</div>
    {selected&&<><h4>实验 {selected.id.slice(0,8)} · {selected.status}</h4>{selected.error&&<p className="agent-error">{selected.error}</p>}<pre>{JSON.stringify(selected.report.metrics??selected.report.progress,null,2)}</pre>
      {['pending','running'].includes(selected.status)&&<button disabled={busy} onClick={()=>void perform(async()=>{await api('/service/experiments/'+selected.id+'/cancel',{method:'POST'});await load(selected.id)})}>取消实验</button>}
      {selected.status==='completed'&&<><button onClick={download}>下载完整报告</button><label>与完成的实验比较<select defaultValue="" onChange={e=>{const id=e.target.value;if(id)void perform(async()=>setComparison(await api('/service/experiments/'+selected.id+'/compare/'+id)))}}><option value="">选择基线</option>{experiments.filter(e=>e.id!==selected.id&&e.status==='completed').map(e=><option key={e.id} value={e.id}>{e.id.slice(0,8)} · {e.config.split}</option>)}</select></label>{comparison!==null&&<pre>{JSON.stringify(comparison,null,2)}</pre>}</>}
      {selected.report.rows?.map((row,index)=><details className="agent-trace" key={row.id+'-'+index}><summary>{row.id} · {row.contract_pass?'契约通过':'契约失败'} · {row.text}</summary><p>事实标准：{row.human_review.rubric}</p><pre>{JSON.stringify(row.result,null,2)}</pre><p>已保存评分：{row.human_review.factual_correct===null?'待复核':row.human_review.factual_correct?'正确':'错误'}</p><label>复核说明<textarea maxLength={2000} rows={2} value={reviews[index]??row.human_review.notes} onChange={e=>setReviews({...reviews,[index]:e.target.value})}/></label><button disabled={busy} onClick={()=>void saveScore(index,true)}>保存：正确</button><button disabled={busy} onClick={()=>void saveScore(index,false)}>保存：错误</button><button disabled={busy} onClick={()=>void saveScore(index,null)}>重置为待复核</button><details><summary>调用轨迹</summary><pre>{JSON.stringify(row.trace,null,2)}</pre></details></details>)}
    </>}
  </section>
}
