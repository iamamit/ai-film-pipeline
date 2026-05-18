import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { X, Loader2 } from 'lucide-react'
import { api } from '../api/client'
import type { CreateProjectPayload } from '../types'

const TONES = ['dramatic', 'inspirational', 'educational', 'epic', 'biographical', 'investigative']
const STYLES = ['documentary', 'cinematic', 'biographical', 'journalistic']

interface Props {
  onClose: () => void
}

export function CreateProjectModal({ onClose }: Props) {
  const qc = useQueryClient()
  const [form, setForm] = useState<CreateProjectPayload>({
    topic: '',
    duration_minutes: 10,
    tone: 'dramatic',
    style: 'documentary',
  })
  const [error, setError] = useState<string | null>(null)

  const create = useMutation({
    mutationFn: api.projects.create,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['projects'] })
      onClose()
    },
    onError: (err: Error) => setError(err.message),
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!form.topic.trim()) { setError('Topic is required'); return }
    setError(null)
    create.mutate(form)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-lg rounded-2xl border border-slate-700 bg-slate-900 shadow-2xl">
        {/* header */}
        <div className="flex items-center justify-between border-b border-slate-800 px-6 py-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-100">New Film Project</h2>
            <p className="text-sm text-slate-400">AI will research, script, and produce your documentary</p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-200 transition-colors">
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* form */}
        <form onSubmit={handleSubmit} className="px-6 py-5 space-y-5">
          {/* topic */}
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1.5">Topic</label>
            <textarea
              rows={2}
              placeholder="e.g. The Fall of the Berlin Wall"
              value={form.topic}
              onChange={e => setForm(f => ({ ...f, topic: e.target.value }))}
              className="w-full rounded-lg border border-slate-700 bg-slate-800 px-4 py-2.5 text-sm text-slate-100 placeholder-slate-500 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 resize-none transition-colors"
            />
          </div>

          {/* duration */}
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1.5">
              Duration — <span className="text-indigo-400">{form.duration_minutes} minutes</span>
            </label>
            <input
              type="range"
              min={1} max={60} step={1}
              value={form.duration_minutes}
              onChange={e => setForm(f => ({ ...f, duration_minutes: Number(e.target.value) }))}
              className="w-full accent-indigo-500"
            />
            <div className="flex justify-between text-xs text-slate-500 mt-1">
              <span>1 min</span><span>60 min</span>
            </div>
          </div>

          {/* tone + style */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1.5">Tone</label>
              <select
                value={form.tone}
                onChange={e => setForm(f => ({ ...f, tone: e.target.value }))}
                className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2.5 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 transition-colors"
              >
                {TONES.map(t => <option key={t} value={t} className="capitalize">{t.charAt(0).toUpperCase() + t.slice(1)}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1.5">Style</label>
              <select
                value={form.style}
                onChange={e => setForm(f => ({ ...f, style: e.target.value }))}
                className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2.5 text-sm text-slate-100 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 transition-colors"
              >
                {STYLES.map(s => <option key={s} value={s} className="capitalize">{s.charAt(0).toUpperCase() + s.slice(1)}</option>)}
              </select>
            </div>
          </div>

          {error && (
            <p className="text-sm text-red-400 bg-red-500/5 rounded-lg px-3 py-2 ring-1 ring-red-500/20">{error}</p>
          )}

          {/* actions */}
          <div className="flex justify-end gap-3 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg px-4 py-2 text-sm font-medium text-slate-400 hover:text-slate-200 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={create.isPending}
              className="flex items-center gap-2 rounded-lg bg-indigo-600 px-5 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-60 disabled:cursor-not-allowed transition-colors"
            >
              {create.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              {create.isPending ? 'Creating…' : 'Create Project'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
