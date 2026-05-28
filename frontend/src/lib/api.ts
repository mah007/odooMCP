const BASE = '/api'

function getToken(): string | null {
  return localStorage.getItem('token')
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken()
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers ?? {}),
    },
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail ?? 'Request failed')
  }
  if (res.status === 204) return undefined as T
  return res.json()
}

// Auth
export const api = {
  auth: {
    status: () => request<{ setup_done: boolean }>('/auth/status'),
    setup: (username: string, password: string) =>
      request<{ token: string }>('/auth/setup', {
        method: 'POST',
        body: JSON.stringify({ username, password }),
      }),
    login: (username: string, password: string) =>
      request<{ token: string }>('/auth/login', {
        method: 'POST',
        body: JSON.stringify({ username, password }),
      }),
  },

  connections: {
    list: () => request<Connection[]>('/connections'),
    create: (data: ConnectionCreate) =>
      request<Connection>('/connections', { method: 'POST', body: JSON.stringify(data) }),
    update: (id: number, data: Partial<ConnectionCreate>) =>
      request<Connection>(`/connections/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
    delete: (id: number) => request<void>(`/connections/${id}`, { method: 'DELETE' }),
    test: (id: number) => request<Connection>(`/connections/${id}/test`, { method: 'POST' }),
    activate: (id: number) => request<Connection>(`/connections/${id}/activate`, { method: 'POST' }),
  },

  apiKeys: {
    list: () => request<ApiKeyRow[]>('/api-keys'),
    create: (name: string) =>
      request<ApiKeyRow & { key: string }>('/api-keys', {
        method: 'POST',
        body: JSON.stringify({ name }),
      }),
    revoke: (id: number) => request<void>(`/api-keys/${id}`, { method: 'DELETE' }),
  },

  dashboard: {
    get: () => request<DashboardData>('/dashboard'),
  },
}

// Types
export interface Connection {
  id: number
  name: string
  url: string
  database: string
  username: string
  credential_type: 'api_key' | 'password'
  is_active: boolean
  status: 'untested' | 'ok' | 'error'
  last_tested_at: string | null
  last_error: string | null
  created_at: string | null
}

export interface ConnectionCreate {
  name: string
  url: string
  database: string
  username: string
  credential: string
  credential_type: 'api_key' | 'password'
}

export interface ApiKeyRow {
  id: number
  name: string
  key_prefix: string
  is_active: boolean
  created_at: string | null
  last_used_at: string | null
  request_count: number
}

export interface DashboardData {
  total_requests: number
  total_errors: number
  active_connections: number
  active_keys: number
  tool_stats: { tool: string; count: number }[]
  recent_logs: {
    id: number
    timestamp: string | null
    tool_name: string
    status: 'success' | 'error'
    duration_ms: number
    error_message: string | null
  }[]
}
