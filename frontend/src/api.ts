const BASE = import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8000/api/v1'

export async function bootstrapSession() {
  const response = await fetch(`${BASE}/auth/login`, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({email:'demo@agentflow.dev',password:'demo1234'}) })
  if (!response.ok) throw new Error('Unable to login to demo account')
  const data = await response.json()
  localStorage.setItem('agentflow_token', data.access_token)
}

export async function api(path: string, init: RequestInit = {}) {
  const token = localStorage.getItem('agentflow_token')
  const response = await fetch(`${BASE}${path}`, { ...init, headers:{'Content-Type':'application/json', ...(token ? {Authorization:`Bearer ${token}`} : {}), ...(init.headers ?? {})} })
  if (!response.ok) throw new Error((await response.text()) || `Request failed: ${response.status}`)
  return response.json()
}
