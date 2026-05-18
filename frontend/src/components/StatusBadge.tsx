import { clsx } from 'clsx'
import type { ProjectStatus } from '../types'

const CONFIG: Record<ProjectStatus, { label: string; classes: string; dot: string }> = {
  pending:           { label: 'Pending',           classes: 'bg-amber-500/10 text-amber-400 ring-amber-500/20',    dot: 'bg-amber-400' },
  processing:        { label: 'Processing',        classes: 'bg-blue-500/10 text-blue-400 ring-blue-500/20',       dot: 'bg-blue-400 animate-pulse' },
  researching:       { label: 'Researching',       classes: 'bg-blue-500/10 text-blue-400 ring-blue-500/20',       dot: 'bg-blue-400 animate-pulse' },
  scripting:         { label: 'Scripting',         classes: 'bg-violet-500/10 text-violet-400 ring-violet-500/20', dot: 'bg-violet-400 animate-pulse' },
  storyboarding:     { label: 'Storyboarding',     classes: 'bg-violet-500/10 text-violet-400 ring-violet-500/20', dot: 'bg-violet-400 animate-pulse' },
  generating_assets: { label: 'Generating Assets', classes: 'bg-cyan-500/10 text-cyan-400 ring-cyan-500/20',       dot: 'bg-cyan-400 animate-pulse' },
  assembling:        { label: 'Assembling',        classes: 'bg-cyan-500/10 text-cyan-400 ring-cyan-500/20',       dot: 'bg-cyan-400 animate-pulse' },
  completed:         { label: 'Completed',         classes: 'bg-emerald-500/10 text-emerald-400 ring-emerald-500/20', dot: 'bg-emerald-400' },
  failed:            { label: 'Failed',            classes: 'bg-red-500/10 text-red-400 ring-red-500/20',          dot: 'bg-red-400' },
  cancelled:         { label: 'Cancelled',         classes: 'bg-slate-500/10 text-slate-400 ring-slate-500/20',    dot: 'bg-slate-400' },
}

export function StatusBadge({ status }: { status: ProjectStatus }) {
  const cfg = CONFIG[status] ?? CONFIG.pending
  return (
    <span className={clsx('inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset', cfg.classes)}>
      <span className={clsx('h-1.5 w-1.5 rounded-full', cfg.dot)} />
      {cfg.label}
    </span>
  )
}
