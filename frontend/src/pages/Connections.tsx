import { useEffect, useState } from 'react'
import { api, type Connection, type ConnectionCreate } from '../lib/api'

const STATUS_BADGE: Record<string, string> = {
  ok: 'bg-green-100 text-green-700',
  error: 'bg-red-100 text-red-700',
  untested: 'bg-gray-100 text-gray-600',
}

function Modal({
  title,
  onClose,
  children,
}: {
  title: string
  onClose: () => void
  children: React.ReactNode
}) {
  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-lg p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-gray-900">{title}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">✕</button>
        </div>
        {children}
      </div>
    </div>
  )
}

type FormState = Omit<ConnectionCreate, never>

const EMPTY_FORM: FormState = {
  name: '',
  url: '',
  database: '',
  username: '',
  credential: '',
  credential_type: 'api_key',
}

export default function Connections() {
  const [conns, setConns] = useState<Connection[]>([])
  const [showModal, setShowModal] = useState(false)
  const [editConn, setEditConn] = useState<Connection | null>(null)
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState<number | null>(null)
  const [activating, setActivating] = useState<number | null>(null)
  const [error, setError] = useState('')

  function load() {
    api.connections.list().then(setConns).catch(e => setError(e.message))
  }

  useEffect(() => { load() }, [])

  function openAdd() {
    setEditConn(null)
    setForm(EMPTY_FORM)
    setShowModal(true)
  }

  function openEdit(c: Connection) {
    setEditConn(c)
    setForm({
      name: c.name,
      url: c.url,
      database: c.database,
      username: c.username,
      credential: '',
      credential_type: c.credential_type,
    })
    setShowModal(true)
  }

  async function save(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    try {
      if (editConn) {
        const update: Partial<ConnectionCreate> = { ...form }
        if (!update.credential) delete update.credential
        await api.connections.update(editConn.id, update)
      } else {
        await api.connections.create(form)
      }
      setShowModal(false)
      load()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  async function testConn(id: number) {
    setTesting(id)
    try {
      const updated = await api.connections.test(id)
      setConns(prev => prev.map(c => (c.id === id ? updated : c)))
    } finally {
      setTesting(null)
    }
  }

  async function activateConn(id: number) {
    setActivating(id)
    try {
      await api.connections.activate(id)
      load()
    } finally {
      setActivating(null)
    }
  }

  async function deleteConn(id: number) {
    if (!confirm('Delete this connection?')) return
    await api.connections.delete(id)
    load()
  }

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-xl font-bold text-gray-900">Odoo Connections</h2>
        <button
          onClick={openAdd}
          className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700"
        >
          + Add Connection
        </button>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
          {error}
        </div>
      )}

      <div className="bg-white rounded-xl border border-gray-200">
        {conns.length === 0 ? (
          <p className="px-5 py-8 text-center text-gray-400 text-sm">
            No connections yet. Add one to get started.
          </p>
        ) : (
          <div className="divide-y divide-gray-100">
            {conns.map(c => (
              <div key={c.id} className="px-5 py-4 flex items-center gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-gray-900 text-sm">{c.name}</span>
                    {c.is_active && (
                      <span className="bg-blue-100 text-blue-700 text-xs px-2 py-0.5 rounded-full font-medium">
                        Active
                      </span>
                    )}
                    <span className={`text-xs px-2 py-0.5 rounded-full ${STATUS_BADGE[c.status] ?? STATUS_BADGE.untested}`}>
                      {c.status}
                    </span>
                  </div>
                  <p className="text-xs text-gray-400 mt-0.5 truncate">
                    {c.url} · {c.database} · {c.username}
                  </p>
                  {c.last_error && (
                    <p className="text-xs text-red-500 mt-0.5 truncate">{c.last_error}</p>
                  )}
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <button
                    onClick={() => testConn(c.id)}
                    disabled={testing === c.id}
                    className="text-xs px-3 py-1.5 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-50"
                  >
                    {testing === c.id ? 'Testing…' : 'Test'}
                  </button>
                  {!c.is_active && (
                    <button
                      onClick={() => activateConn(c.id)}
                      disabled={activating === c.id}
                      className="text-xs px-3 py-1.5 rounded-lg border border-green-200 text-green-700 hover:bg-green-50 disabled:opacity-50"
                    >
                      {activating === c.id ? 'Activating…' : 'Activate'}
                    </button>
                  )}
                  <button
                    onClick={() => openEdit(c)}
                    className="text-xs px-3 py-1.5 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50"
                  >
                    Edit
                  </button>
                  <button
                    onClick={() => deleteConn(c.id)}
                    className="text-xs px-3 py-1.5 rounded-lg border border-red-200 text-red-600 hover:bg-red-50"
                  >
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {showModal && (
        <Modal title={editConn ? 'Edit Connection' : 'New Connection'} onClose={() => setShowModal(false)}>
          <form onSubmit={save} className="space-y-3">
            {(['name', 'url', 'database', 'username'] as const).map(field => (
              <div key={field}>
                <label className="block text-xs font-medium text-gray-600 mb-1 capitalize">{field}</label>
                <input
                  type="text"
                  required={field !== 'name' || !editConn}
                  value={form[field]}
                  onChange={e => setForm(f => ({ ...f, [field]: e.target.value }))}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
            ))}
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Credential Type</label>
              <select
                value={form.credential_type}
                onChange={e => setForm(f => ({ ...f, credential_type: e.target.value as 'api_key' | 'password' }))}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="api_key">API Key</option>
                <option value="password">Password</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">
                {form.credential_type === 'api_key' ? 'API Key' : 'Password'}
                {editConn && ' (leave blank to keep current)'}
              </label>
              <input
                type="password"
                required={!editConn}
                value={form.credential}
                onChange={e => setForm(f => ({ ...f, credential: e.target.value }))}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setShowModal(false)}
                className="px-4 py-2 text-sm rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={saving}
                className="px-4 py-2 text-sm rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {saving ? 'Saving…' : 'Save'}
              </button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  )
}
