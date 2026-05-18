import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Plus, Film, CheckCircle2, Clock, AlertCircle, Loader2 } from 'lucide-react'
import { api } from '../api/client'
import { ProjectCard } from '../components/ProjectCard'
import { CreateProjectModal } from '../components/CreateProjectModal'
import type { ProjectStatus } from '../types'

const ACTIVE_STATUSES: ProjectStatus[] = ['processing', 'researching', 'scripting', 'storyboarding', 'generating_assets', 'assembling']

export function Dashboard() {
  const [showCreate, setShowCreate] = useState(false)
  const [filter, setFilter] = useState<'all' | 'active' | 'completed' | 'failed'>('all')

  const { data, isLoading, error } = useQuery({
    queryKey: ['projects'],
    queryFn: () => api.projects.list(50),
    refetchInterval: 4_000,
  })

  const projects = data?.items ?? []

  const stats = {
    total: data?.total ?? 0,
    active: projects.filter(p => ACTIVE_STATUSES.includes(p.status)).length,
    completed: projects.filter(p => p.status === 'completed').length,
    failed: projects.filter(p => p.status === 'failed').length,
  }

  const filtered = projects.filter(p => {
    if (filter === 'active') return ACTIVE_STATUSES.includes(p.status)
    if (filter === 'completed') return p.status === 'completed'
    if (filter === 'failed') return p.status === 'failed'
    return true
  })

  return (
    <div className="min-h-screen bg-slate-950">
      {/* hero header */}
      <div className="border-b border-slate-800 bg-slate-950/80 backdrop-blur-sm sticky top-0 z-10">
        <div className="mx-auto max-w-6xl px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600">
              <Film className="h-4 w-4 text-white" />
            </div>
            <div>
              <h1 className="text-sm font-semibold text-slate-100">AI Film Pipeline</h1>
              <p className="text-xs text-slate-500">Documentary generation platform</p>
            </div>
          </div>
          <button
            onClick={() => setShowCreate(true)}
            className="flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 transition-colors"
          >
            <Plus className="h-4 w-4" />
            New Project
          </button>
        </div>
      </div>

      <div className="mx-auto max-w-6xl px-6 py-8 space-y-8">
        {/* stats */}
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          {[
            { label: 'Total Projects', value: stats.total, icon: Film, color: 'text-indigo-400', bg: 'bg-indigo-500/10' },
            { label: 'In Progress', value: stats.active, icon: Loader2, color: 'text-blue-400', bg: 'bg-blue-500/10' },
            { label: 'Completed', value: stats.completed, icon: CheckCircle2, color: 'text-emerald-400', bg: 'bg-emerald-500/10' },
            { label: 'Failed', value: stats.failed, icon: AlertCircle, color: 'text-red-400', bg: 'bg-red-500/10' },
          ].map(s => (
            <div key={s.label} className="rounded-xl border border-slate-800 bg-slate-900 p-4 flex items-center gap-3">
              <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${s.bg}`}>
                <s.icon className={`h-5 w-5 ${s.color}`} />
              </div>
              <div>
                <p className="text-2xl font-bold text-slate-100">{s.value}</p>
                <p className="text-xs text-slate-400">{s.label}</p>
              </div>
            </div>
          ))}
        </div>

        {/* filters + project list */}
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex gap-1 rounded-lg bg-slate-900 p-1 ring-1 ring-slate-800">
              {(['all', 'active', 'completed', 'failed'] as const).map(f => (
                <button
                  key={f}
                  onClick={() => setFilter(f)}
                  className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors capitalize ${
                    filter === f
                      ? 'bg-slate-700 text-slate-100'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  {f}
                </button>
              ))}
            </div>
            <p className="text-xs text-slate-500">{filtered.length} project{filtered.length !== 1 ? 's' : ''}</p>
          </div>

          {isLoading && (
            <div className="flex items-center justify-center py-16">
              <Loader2 className="h-6 w-6 animate-spin text-slate-500" />
            </div>
          )}

          {error && (
            <div className="rounded-xl border border-red-500/20 bg-red-500/5 p-6 text-center">
              <p className="text-sm text-red-400">Failed to load projects — is the API running?</p>
            </div>
          )}

          {!isLoading && !error && filtered.length === 0 && (
            <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-slate-800 py-16 gap-4">
              <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-slate-900 ring-1 ring-slate-800">
                <Film className="h-6 w-6 text-slate-600" />
              </div>
              <div className="text-center">
                <p className="text-sm font-medium text-slate-300">No projects yet</p>
                <p className="text-xs text-slate-500 mt-1">Create your first documentary to get started</p>
              </div>
              <button
                onClick={() => setShowCreate(true)}
                className="flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 transition-colors"
              >
                <Plus className="h-4 w-4" />
                New Project
              </button>
            </div>
          )}

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {filtered.map(p => <ProjectCard key={p.id} project={p} />)}
          </div>
        </div>
      </div>

      {showCreate && <CreateProjectModal onClose={() => setShowCreate(false)} />}
    </div>
  )
}
