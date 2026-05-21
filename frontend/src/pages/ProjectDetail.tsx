import { useParams, useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Film, Clock, DollarSign, Calendar, XCircle, Loader2, CheckCircle2, Circle, AlertCircle, ScrollText, Clapperboard } from 'lucide-react'
import { clsx } from 'clsx'
import { api } from '../api/client'
import { StatusBadge } from '../components/StatusBadge'
import { ProgressBar } from '../components/ProgressBar'
import { PHASES } from '../types'

function fmt(iso: string) {
  return new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function PhaseIcon({ state }: { state: 'done' | 'active' | 'upcoming' }) {
  if (state === 'done') return <CheckCircle2 className="h-5 w-5 text-emerald-400" />
  if (state === 'active') return <Loader2 className="h-5 w-5 text-indigo-400 animate-spin" />
  return <Circle className="h-5 w-5 text-slate-600" />
}

function phaseState(progress: number, range: [number, number], status: string): 'done' | 'active' | 'upcoming' {
  if (status === 'completed') return 'done'
  if (progress >= range[1]) return 'done'
  if (progress >= range[0]) return 'active'
  return 'upcoming'
}

export function ProjectDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const qc = useQueryClient()

  const { data: project, isLoading, error } = useQuery({
    queryKey: ['project', id],
    queryFn: () => api.projects.get(id!),
    refetchInterval: 3_000,
    enabled: !!id,
  })

  const cancel = useMutation({
    mutationFn: () => api.projects.cancel(id!),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['projects'] })
      qc.invalidateQueries({ queryKey: ['project', id] })
    },
  })

  const { data: script } = useQuery({
    queryKey: ['script', id],
    queryFn: () => api.projects.script(id!),
    enabled: !!id && project?.status === 'completed',
    retry: false,
  })

  const { data: storyboard } = useQuery({
    queryKey: ['storyboard', id],
    queryFn: () => api.projects.storyboard(id!),
    enabled: !!id && project?.status === 'completed',
    retry: false,
  })

  if (isLoading) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-slate-500" />
      </div>
    )
  }

  if (error || !project) {
    return (
      <div className="min-h-screen bg-slate-950 flex flex-col items-center justify-center gap-4">
        <AlertCircle className="h-8 w-8 text-red-400" />
        <p className="text-slate-400">Project not found</p>
        <button onClick={() => navigate('/')} className="text-indigo-400 hover:text-indigo-300 text-sm">
          Back to Dashboard
        </button>
      </div>
    )
  }

  const canCancel = ['pending', 'processing'].includes(project.status)

  return (
    <div className="min-h-screen bg-slate-950">
      {/* navbar */}
      <div className="border-b border-slate-800 bg-slate-950/80 backdrop-blur-sm sticky top-0 z-10">
        <div className="mx-auto max-w-4xl px-6 py-4 flex items-center justify-between">
          <button
            onClick={() => navigate('/')}
            className="flex items-center gap-2 text-slate-400 hover:text-slate-200 text-sm transition-colors"
          >
            <ArrowLeft className="h-4 w-4" />
            Dashboard
          </button>
          {canCancel && (
            <button
              onClick={() => cancel.mutate()}
              disabled={cancel.isPending}
              className="flex items-center gap-1.5 text-sm text-slate-400 hover:text-red-400 transition-colors disabled:opacity-50"
            >
              <XCircle className="h-4 w-4" />
              Cancel Project
            </button>
          )}
        </div>
      </div>

      <div className="mx-auto max-w-4xl px-6 py-8 space-y-6">
        {/* hero */}
        <div className="rounded-2xl border border-slate-800 bg-slate-900 p-6 space-y-5">
          <div className="flex items-start justify-between gap-4">
            <div className="flex items-start gap-4">
              <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-indigo-500/10 ring-1 ring-indigo-500/20">
                <Film className="h-6 w-6 text-indigo-400" />
              </div>
              <div>
                <h1 className="text-xl font-bold text-slate-100 leading-snug">{project.topic}</h1>
                <p className="text-sm text-slate-400 mt-1">
                  {project.current_phase ? `Currently: ${project.current_phase}` : 'Queued for processing'}
                </p>
              </div>
            </div>
            <StatusBadge status={project.status} />
          </div>

          <ProgressBar progress={project.progress} status={project.status} />

          {/* meta grid */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              { icon: Clock, label: 'Duration', value: `${project.duration_minutes} min` },
              { icon: DollarSign, label: 'Cost so far', value: `$${project.total_cost}` },
              { icon: Calendar, label: 'Created', value: fmt(project.created_at) },
              { icon: Calendar, label: 'Completed', value: project.completed_at ? fmt(project.completed_at) : '—' },
            ].map(m => (
              <div key={m.label} className="rounded-lg bg-slate-800/50 p-3">
                <div className="flex items-center gap-1.5 mb-1">
                  <m.icon className="h-3.5 w-3.5 text-slate-500" />
                  <span className="text-xs text-slate-500">{m.label}</span>
                </div>
                <p className="text-sm font-medium text-slate-200 truncate">{m.value}</p>
              </div>
            ))}
          </div>

          {project.error_message && (
            <div className="rounded-lg border border-red-500/20 bg-red-500/5 px-4 py-3">
              <p className="text-sm text-red-400">{project.error_message}</p>
            </div>
          )}
        </div>

        {/* phase timeline */}
        <div className="rounded-2xl border border-slate-800 bg-slate-900 p-6">
          <h2 className="text-sm font-semibold text-slate-300 mb-5">Production Pipeline</h2>
          <div className="space-y-0">
            {PHASES.map((phase, i) => {
              const state = phaseState(project.progress, phase.progressRange, project.status)
              const isLast = i === PHASES.length - 1
              return (
                <div key={phase.key} className="flex gap-4">
                  {/* connector */}
                  <div className="flex flex-col items-center">
                    <PhaseIcon state={state} />
                    {!isLast && (
                      <div className={clsx(
                        'w-px flex-1 my-1',
                        state === 'done' ? 'bg-emerald-500/30' : 'bg-slate-800'
                      )} style={{ minHeight: 28 }} />
                    )}
                  </div>
                  {/* content */}
                  <div className={clsx('pb-6', isLast && 'pb-0')}>
                    <p className={clsx(
                      'text-sm font-medium leading-none',
                      state === 'done' && 'text-emerald-400',
                      state === 'active' && 'text-indigo-300',
                      state === 'upcoming' && 'text-slate-500',
                    )}>
                      {phase.label}
                      <span className="ml-2 text-xs font-normal opacity-60">
                        {phase.progressRange[0]}–{phase.progressRange[1]}%
                      </span>
                    </p>
                    <p className={clsx(
                      'text-xs mt-1',
                      state === 'upcoming' ? 'text-slate-600' : 'text-slate-400',
                    )}>
                      {phase.description}
                    </p>
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        {/* script */}
        {script && (
          <div className="rounded-2xl border border-slate-800 bg-slate-900 p-6 space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <ScrollText className="h-4 w-4 text-indigo-400" />
                <h2 className="text-sm font-semibold text-slate-300">Generated Script</h2>
              </div>
              <span className="text-xs text-slate-500">{script.scenes} scenes</span>
            </div>
            <pre className="text-xs text-slate-300 whitespace-pre-wrap leading-relaxed bg-slate-950 rounded-lg p-4 overflow-auto max-h-[600px]">
              {script.content}
            </pre>
          </div>
        )}

        {/* storyboard */}
        {storyboard && storyboard.scenes.length > 0 && (
          <div className="rounded-2xl border border-slate-800 bg-slate-900 p-6 space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Clapperboard className="h-4 w-4 text-violet-400" />
                <h2 className="text-sm font-semibold text-slate-300">Storyboard</h2>
              </div>
              <span className="text-xs text-slate-500">{storyboard.total_scenes} scenes</span>
            </div>
            <div className="space-y-4">
              {storyboard.scenes.map(scene => (
                <details key={scene.scene_number} className="group rounded-lg border border-slate-700 bg-slate-800/50">
                  <summary className="flex items-center justify-between px-4 py-3 cursor-pointer list-none">
                    <span className="text-sm font-medium text-slate-200">Scene {scene.scene_number}</span>
                    <span className="text-xs text-slate-500 group-open:hidden">Expand</span>
                    <span className="text-xs text-slate-500 hidden group-open:inline">Collapse</span>
                  </summary>
                  <div className="px-4 pb-4 space-y-3">
                    <p className="text-xs text-slate-400 italic border-l-2 border-slate-600 pl-3">
                      {scene.scene_text.slice(0, 200)}...
                    </p>
                    <pre className="text-xs text-slate-300 whitespace-pre-wrap leading-relaxed bg-slate-950 rounded-lg p-3">
                      {scene.storyboard}
                    </pre>
                  </div>
                </details>
              ))}
            </div>
          </div>
        )}

        {/* raw data */}
        <details className="rounded-2xl border border-slate-800 bg-slate-900 p-6 group">
          <summary className="text-sm font-semibold text-slate-300 cursor-pointer list-none flex items-center justify-between">
            Raw Project Data
            <span className="text-xs text-slate-500 group-open:hidden">Show</span>
            <span className="text-xs text-slate-500 hidden group-open:inline">Hide</span>
          </summary>
          <pre className="mt-4 text-xs text-slate-400 overflow-auto rounded-lg bg-slate-950 p-4 leading-relaxed">
            {JSON.stringify(project, null, 2)}
          </pre>
        </details>
      </div>
    </div>
  )
}
