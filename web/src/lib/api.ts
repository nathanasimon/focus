import type { Commitment, Email, SearchResult, Sprint, SyncResponse, Task } from './types'

const BASE = '/api'

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

export const api = {
  needsReply: () => get<Email[]>('/emails/needs-reply'),
  tasks: (status?: string) =>
    get<Task[]>(`/tasks${status ? `?status=${status}` : ''}`),
  commitments: (status = 'open') =>
    get<Commitment[]>(`/commitments?status=${status}`),
  sprints: () => get<Sprint[]>('/sprints?active_only=true'),
  sync: () => post<SyncResponse>('/sync', { process: true }),
  search: (q: string) => get<SearchResult[]>(`/search?q=${encodeURIComponent(q)}`),
}
