import type { CreateProjectPayload, HealthResponse, Project, ProjectListResponse, ReadyResponse } from '../types'

// Hardcoded for Phase 1 — replaced with real auth in a later phase
const USER_ID = '550e8400-e29b-41d4-a716-446655440000'

const BASE = '/api/v1'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      'X-User-ID': USER_ID,
      ...init?.headers,
    },
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail ?? `HTTP ${res.status}`)
  }
  return res.json()
}

export const api = {
  health: () => request<HealthResponse>('/health'),
  ready: () => request<ReadyResponse>('/ready'),

  projects: {
    list: (limit = 50, offset = 0) =>
      request<ProjectListResponse>(`${BASE}/projects?limit=${limit}&offset=${offset}`),

    get: (id: string) =>
      request<Project>(`${BASE}/projects/${id}`),

    create: (payload: CreateProjectPayload) =>
      request<Project>(`${BASE}/projects`, {
        method: 'POST',
        body: JSON.stringify(payload),
      }),

    cancel: (id: string) =>
      request<Project>(`${BASE}/projects/${id}`, { method: 'DELETE' }),
  },
}
