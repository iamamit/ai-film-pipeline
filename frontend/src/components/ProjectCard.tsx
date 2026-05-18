import { useNavigate } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Film, Clock, DollarSign, XCircle, ChevronRight } from 'lucide-react'
import { clsx } from 'clsx'
import type { Project } from '../types'
import { api } from '../api/client'
import { StatusBadge } from './StatusBadge'
import { ProgressBar } from './ProgressBar'

function fmt(iso: string) {
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

export function ProjectCard({ project }: { project: Project }) {
  const navigate = useNavigate()
  const qc = useQueryClient()

  const cancel = useMutation({
    mutationFn: () => api.projects.cancel(project.id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['projects'] }),
  })

  const canCancel = ['pending', 'processing'].includes(project.status)

  return (
    <div
      onClick={() => navigate(`/projects/${project.id}`)}
      className="group relative flex flex-col gap-4 rounded-xl border border-slate-800 bg-slate-900 p-5 cursor-pointer hover:border-slate-700 hover:bg-slate-800/60 transition-all duration-200"
    >
      {/* header */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-indigo-500/10 ring-1 ring-indigo-500/20">
            <Film className="h-4 w-4 text-indigo-400" />
          </div>
          <div className="min-w-0">
            <p className="font-medium text-slate-100 truncate leading-snug">{project.topic}</p>
            <p className="text-xs text-slate-500 mt-0.5">{fmt(project.created_at)}</p>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <StatusBadge status={project.status} />
          <ChevronRight className="h-4 w-4 text-slate-600 group-hover:text-slate-400 transition-colors" />
        </div>
      </div>

      {/* progress */}
      <ProgressBar progress={project.progress} status={project.status} />

      {/* meta row */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4 text-xs text-slate-400">
          <span className="flex items-center gap-1">
            <Clock className="h-3 w-3" />
            {project.duration_minutes} min
          </span>
          <span className="flex items-center gap-1">
            <DollarSign className="h-3 w-3" />
            ${project.total_cost}
          </span>
          {project.tone && (
            <span className="rounded-full bg-slate-800 px-2 py-0.5 capitalize ring-1 ring-slate-700">
              {project.tone}
            </span>
          )}
        </div>

        {canCancel && (
          <button
            onClick={e => { e.stopPropagation(); cancel.mutate() }}
            disabled={cancel.isPending}
            className={clsx(
              'flex items-center gap-1 text-xs text-slate-500 hover:text-red-400 transition-colors',
              cancel.isPending && 'opacity-50 cursor-not-allowed',
            )}
          >
            <XCircle className="h-3.5 w-3.5" />
            Cancel
          </button>
        )}
      </div>

      {project.error_message && (
        <p className="text-xs text-red-400 bg-red-500/5 rounded-lg px-3 py-2 ring-1 ring-red-500/20">
          {project.error_message}
        </p>
      )}
    </div>
  )
}
