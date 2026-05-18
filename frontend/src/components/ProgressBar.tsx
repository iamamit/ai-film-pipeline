import { clsx } from 'clsx'
import type { ProjectStatus } from '../types'

function barColor(status: ProjectStatus) {
  if (status === 'completed') return 'bg-emerald-500'
  if (status === 'failed') return 'bg-red-500'
  if (status === 'cancelled') return 'bg-slate-500'
  return 'bg-indigo-500'
}

export function ProgressBar({ progress, status }: { progress: number; status: ProjectStatus }) {
  const isActive = !['completed', 'failed', 'cancelled', 'pending'].includes(status)
  return (
    <div className="w-full">
      <div className="flex justify-between mb-1">
        <span className="text-xs text-slate-400">Progress</span>
        <span className="text-xs font-medium text-slate-300">{progress}%</span>
      </div>
      <div className="h-1.5 w-full rounded-full bg-slate-700 overflow-hidden">
        <div
          className={clsx('h-full rounded-full transition-all duration-700', barColor(status), isActive && 'animate-pulse-slow')}
          style={{ width: `${Math.max(progress, status === 'pending' ? 0 : 2)}%` }}
        />
      </div>
    </div>
  )
}
