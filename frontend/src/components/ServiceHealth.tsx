import { useQuery } from '@tanstack/react-query'
import { clsx } from 'clsx'
import { api } from '../api/client'

function Dot({ ok }: { ok: boolean }) {
  return (
    <span className={clsx('inline-block h-2 w-2 rounded-full', ok ? 'bg-emerald-400' : 'bg-red-400')} />
  )
}

export function ServiceHealth() {
  const { data } = useQuery({
    queryKey: ['ready'],
    queryFn: api.ready,
    refetchInterval: 10_000,
  })

  const checks = data?.checks ?? {}
  const services = [
    { name: 'API', ok: true },
    { name: 'Database', ok: checks['database'] === 'ok' },
    { name: 'Redis', ok: checks['redis'] === 'ok' },
  ]

  return (
    <div className="flex items-center gap-4">
      {services.map(s => (
        <div key={s.name} className="flex items-center gap-1.5">
          <Dot ok={s.ok} />
          <span className="text-xs text-slate-400">{s.name}</span>
        </div>
      ))}
    </div>
  )
}
