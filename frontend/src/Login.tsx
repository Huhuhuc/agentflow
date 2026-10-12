import {useState} from 'react'
import {BASE} from './api'
import './AgentWorkspace.css'
export default function Login({onSuccess}:{onSuccess:()=>Promise<void>}){
  const [email,setEmail]=useState('')
  const [password,setPassword]=useState('')
  const [error,setError]=useState('')
  const [busy,setBusy]=useState(false)
  return <div className="agent-workspace"><section className="agent-card" style={{maxWidth:460,margin:'60px auto'}}><h2>登录 AgentFlow</h2><p>使用管理员创建的账号。演示环境可使用已有演示账号。</p>{error&&<p role="alert" className="agent-error">{error}</p>}<form onSubmit={e=>{e.preventDefault();setBusy(true);setError('');void(async()=>{const response=await fetch(BASE+'/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email,password})});if(!response.ok)throw new Error('登录失败，请核对账号、密码和服务状态');const data=await response.json();localStorage.setItem('agentflow_token',data.access_token);await onSuccess()})().catch(e=>setError(String(e))).finally(()=>setBusy(false))}}><label>邮箱<input type="email" required autoComplete="username" value={email} onChange={e=>setEmail(e.target.value)}/></label><label>密码<input type="password" required autoComplete="current-password" value={password} onChange={e=>setPassword(e.target.value)}/></label><button className="primary" disabled={busy}>登录</button></form></section></div>
}
