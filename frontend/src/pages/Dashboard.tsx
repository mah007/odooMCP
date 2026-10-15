import { useEffect, useState } from 'react'
import { api, type DashboardData, type TransportMode } from '../lib/api'

function formatBytes(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—'
  if (n < 1024) return `${Math.round(n)} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

function formatMs(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—'
  if (n < 1000) return `${Math.round(n)}ms`
  return `${(n / 1000).toFixed(1)}s`
}

const TRANSPORT_LABEL: Record<TransportMode, string> = { json2: 'JSON-2', xmlrpc: 'XML-RPC' }
const TRANSPORT_BADGE: Record<TransportMode, string> = {
  json2: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  xmlrpc: 'bg-slate-50 text-slate-600 border-slate-200',
}

function StatCard({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <p className="text-sm text-gray-500">{label}</p>
      <p className={`text-3xl font-bold mt-1 ${color}`}>{value.toLocaleString()}</p>
    </div>
  )
}

export default function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api.dashboard.get().then(setData).catch(e => setError(e.message))
    const id = setInterval(() => api.dashboard.get().then(setData).catch(() => {}), 15_000)
    return () => clearInterval(id)
  }, [])

  if (error) return <div className="p-8 text-red-600">{error}</div>
  if (!data) return <div className="p-8 text-gray-500">Loading…</div>

  return (
    <div className="p-8">
      <h2 className="text-xl font-bold text-gray-900 mb-6">Dashboard</h2>

      {/* Stat cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <StatCard label="Total Requests" value={data.total_requests} color="text-gray-900" />
        <StatCard label="Errors" value={data.total_errors} color="text-red-600" />
        <StatCard label="Active Connections" value={data.active_connections} color="text-green-600" />
        <StatCard label="Active API Keys" value={data.active_keys} color="text-blue-600" />
      </div>

      {/* Tool usage */}
      {data.tool_stats.length > 0 && (
        <div className="bg-white rounded-xl border border-gray-200 p-5 mb-6">
          <h3 className="text-sm font-semibold text-gray-700 mb-3">Tool Usage</h3>
          <div className="space-y-2">
            <div className="flex items-center gap-3 text-[10px] text-gray-400 uppercase tracking-wider">
              <span className="w-36">Tool</span>
              <span className="flex-1" />
              <span className="w-8 text-right">Calls</span>
              <span className="w-16 text-right">Avg size</span>
              <span className="w-14 text-right">Avg time</span>
            </div>
            {data.tool_stats.map(t => {
              const pct = data.total_requests > 0 ? Math.round((t.count / data.total_requests) * 100) : 0
              return (
                <div key={t.tool} className="flex items-center gap-3">
                  <span className="w-36 text-sm text-gray-600 truncate">{t.tool}</span>
                  <div className="flex-1 bg-gray-100 rounded-full h-2">
                    <div className="bg-blue-500 h-2 rounded-full" style={{ width: `${pct}%` }} />
                  </div>
                  <span className="text-xs text-gray-500 w-8 text-right">{t.count}</span>
                  <span
                    className="text-xs text-gray-500 w-16 text-right tabular-nums"
                    title={t.max_bytes !== null && t.max_bytes !== undefined ? `Largest response: ${formatBytes(t.max_bytes)}` : undefined}
                  >
                    {formatBytes(t.avg_bytes)}
                  </span>
                  <span className="text-xs text-gray-500 w-14 text-right tabular-nums">{formatMs(t.avg_ms)}</span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Recent logs */}
      <div className="bg-white rounded-xl border border-gray-200">
        <div className="px-5 py-4 border-b border-gray-100">
          <h3 className="text-sm font-semibold text-gray-700">Recent Requests</h3>
        </div>
        {data.recent_logs.length === 0 ? (
          <p className="px-5 py-8 text-center text-gray-400 text-sm">No requests yet</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 text-left text-xs text-gray-400 uppercase tracking-wider">
                  <th className="px-5 py-3">Time</th>
                  <th className="px-5 py-3">Tool</th>
                  <th className="px-5 py-3">Status</th>
                  <th className="px-5 py-3">Duration</th>
                  <th className="px-5 py-3">Size</th>
                  <th className="px-5 py-3">Transport</th>
                  <th className="px-5 py-3">Error</th>
                </tr>
              </thead>
              <tbody>
                {data.recent_logs.map(log => (
                  <tr key={log.id} className="border-b border-gray-50 hover:bg-gray-50">
                    <td className="px-5 py-3 text-gray-500 whitespace-nowrap">
                      {log.timestamp ? new Date(log.timestamp).toLocaleTimeString() : '—'}
                    </td>
                    <td className="px-5 py-3 font-mono text-gray-700">{log.tool_name}</td>
                    <td className="px-5 py-3">
                      <span
                        className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                          log.status === 'success'
                            ? 'bg-green-100 text-green-700'
                            : 'bg-red-100 text-red-700'
                        }`}
                      >
                        {log.status}
                      </span>
                    </td>
                    <td className="px-5 py-3 text-gray-500">{log.duration_ms}ms</td>
                    <td className="px-5 py-3 text-gray-500 whitespace-nowrap">{formatBytes(log.response_bytes)}</td>
                    <td className="px-5 py-3">
                      {log.transport ? (
                        <span
                          className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border whitespace-nowrap ${TRANSPORT_BADGE[log.transport] ?? 'bg-gray-50 text-gray-500 border-gray-200'}`}
                        >
                          {TRANSPORT_LABEL[log.transport] ?? log.transport}
                        </span>
                      ) : (
                        <span className="text-gray-400">—</span>
                      )}
                    </td>
                    <td className="px-5 py-3 text-red-600 text-xs max-w-xs truncate">
                      {log.error_message ?? ''}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
