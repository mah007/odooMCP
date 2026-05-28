import { useEffect, useState } from 'react'
import { api, type ApiKeyRow } from '../lib/api'

export default function ApiKeys() {
  const [keys, setKeys] = useState<ApiKeyRow[]>([])
  const [newName, setNewName] = useState('')
  const [newKey, setNewKey] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState('')

  function load() {
    api.apiKeys.list().then(setKeys).catch(e => setError(e.message))
  }

  useEffect(() => { load() }, [])

  async function generate(e: React.FormEvent) {
    e.preventDefault()
    if (!newName.trim()) return
    setCreating(true)
    try {
      const result = await api.apiKeys.create(newName.trim())
      setNewKey(result.key)
      setNewName('')
      load()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Create failed')
    } finally {
      setCreating(false)
    }
  }

  async function revoke(id: number) {
    if (!confirm('Revoke this key? Any AI clients using it will stop working.')) return
    await api.apiKeys.revoke(id)
    load()
  }

  function copy() {
    if (newKey) {
      navigator.clipboard.writeText(newKey)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  return (
    <div className="p-8">
      <h2 className="text-xl font-bold text-gray-900 mb-6">API Keys</h2>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">{error}</div>
      )}

      {/* New key banner */}
      {newKey && (
        <div className="mb-6 p-4 bg-green-50 border border-green-200 rounded-xl">
          <p className="text-sm font-semibold text-green-800 mb-1">
            New API key generated — copy it now. It will not be shown again.
          </p>
          <div className="flex items-center gap-2 mt-2">
            <code className="flex-1 bg-white border border-green-300 rounded-lg px-3 py-2 text-xs font-mono text-gray-800 break-all">
              {newKey}
            </code>
            <button
              onClick={copy}
              className="shrink-0 px-3 py-2 bg-green-600 text-white text-xs rounded-lg hover:bg-green-700"
            >
              {copied ? 'Copied!' : 'Copy'}
            </button>
          </div>
          <button
            onClick={() => setNewKey(null)}
            className="mt-2 text-xs text-green-700 underline"
          >
            I've saved it, dismiss
          </button>
        </div>
      )}

      {/* Generate form */}
      <div className="bg-white rounded-xl border border-gray-200 p-5 mb-6">
        <h3 className="text-sm font-semibold text-gray-700 mb-3">Generate New Key</h3>
        <form onSubmit={generate} className="flex gap-3">
          <input
            type="text"
            placeholder="Key name (e.g. n8n-prod)"
            value={newName}
            onChange={e => setNewName(e.target.value)}
            className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <button
            type="submit"
            disabled={creating || !newName.trim()}
            className="px-4 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {creating ? 'Generating…' : 'Generate'}
          </button>
        </form>
      </div>

      {/* Keys table */}
      <div className="bg-white rounded-xl border border-gray-200">
        {keys.length === 0 ? (
          <p className="px-5 py-8 text-center text-gray-400 text-sm">
            No API keys yet. Generate one above to let an AI agent connect.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 text-left text-xs text-gray-400 uppercase tracking-wider">
                  <th className="px-5 py-3">Name</th>
                  <th className="px-5 py-3">Prefix</th>
                  <th className="px-5 py-3">Status</th>
                  <th className="px-5 py-3">Requests</th>
                  <th className="px-5 py-3">Last Used</th>
                  <th className="px-5 py-3">Created</th>
                  <th className="px-5 py-3" />
                </tr>
              </thead>
              <tbody>
                {keys.map(k => (
                  <tr key={k.id} className="border-b border-gray-50 hover:bg-gray-50">
                    <td className="px-5 py-3 font-medium text-gray-900">{k.name}</td>
                    <td className="px-5 py-3 font-mono text-gray-500">{k.key_prefix}…</td>
                    <td className="px-5 py-3">
                      <span
                        className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                          k.is_active ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'
                        }`}
                      >
                        {k.is_active ? 'Active' : 'Revoked'}
                      </span>
                    </td>
                    <td className="px-5 py-3 text-gray-500">{k.request_count.toLocaleString()}</td>
                    <td className="px-5 py-3 text-gray-500">
                      {k.last_used_at ? new Date(k.last_used_at).toLocaleDateString() : '—'}
                    </td>
                    <td className="px-5 py-3 text-gray-500">
                      {k.created_at ? new Date(k.created_at).toLocaleDateString() : '—'}
                    </td>
                    <td className="px-5 py-3">
                      {k.is_active && (
                        <button
                          onClick={() => revoke(k.id)}
                          className="text-xs px-3 py-1.5 rounded-lg border border-red-200 text-red-600 hover:bg-red-50"
                        >
                          Revoke
                        </button>
                      )}
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
