import { useEffect, useState, useRef } from 'react'
import { api, type Connection, type ConnectionCreate } from '../lib/api'

// ── Status dot ──────────────────────────────────────────────────────────────

const STATUS_DOT: Record<string, string> = {
  ok: 'bg-green-400',
  error: 'bg-red-500',
  untested: 'bg-gray-300',
}

const STATUS_LABEL: Record<string, string> = {
  ok: 'Connected',
  error: 'Error',
  untested: 'Untested',
}

function StatusDot({ status }: { status: string }) {
  const color = STATUS_DOT[status] ?? STATUS_DOT.untested
  return (
    <span className="relative flex items-center justify-center w-4 h-4" title={STATUS_LABEL[status] ?? status}>
      {status === 'ok' && (
        <span className={`absolute inline-flex w-full h-full rounded-full ${color} opacity-50 animate-ping`} />
      )}
      <span className={`relative inline-flex w-3 h-3 rounded-full ${color}`} />
    </span>
  )
}

// ── Icons ────────────────────────────────────────────────────────────────────

function IconGlobe({ className = 'w-3.5 h-3.5 shrink-0 text-gray-400' } = {}) {
  return (
    <svg className={className} fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24">
      <circle cx="12" cy="12" r="10" /><path d="M2 12h20M12 2a15.3 15.3 0 0 1 0 20M12 2a15.3 15.3 0 0 0 0 20" />
    </svg>
  )
}

function IconDatabase({ className = 'w-3.5 h-3.5 shrink-0 text-gray-400' } = {}) {
  return (
    <svg className={className} fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24">
      <ellipse cx="12" cy="5" rx="9" ry="3" /><path d="M21 12c0 1.66-4.03 3-9 3S3 13.66 3 12" /><path d="M3 5v14c0 1.66 4.03 3 9 3s9-1.34 9-3V5" />
    </svg>
  )
}

function IconUser({ className = 'w-3.5 h-3.5 shrink-0 text-gray-400' } = {}) {
  return (
    <svg className={className} fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24">
      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" />
    </svg>
  )
}

function IconKey({ className = 'w-3.5 h-3.5 shrink-0 text-gray-400' } = {}) {
  return (
    <svg className={className} fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24">
      <circle cx="7.5" cy="15.5" r="5.5" /><path d="m21 2-9.6 9.6M15.5 7.5l3 3" />
    </svg>
  )
}


function IconTag({ className = 'w-3.5 h-3.5 shrink-0 text-gray-400' } = {}) {
  return (
    <svg className={className} fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24">
      <path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z" /><circle cx="7" cy="7" r="1.5" fill="currentColor" stroke="none" />
    </svg>
  )
}

function IconEye({ open }: { open: boolean }) {
  return open ? (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24">
      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" /><circle cx="12" cy="12" r="3" />
    </svg>
  ) : (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24">
      <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" /><line x1="1" y1="1" x2="23" y2="23" />
    </svg>
  )
}

function IconPlug({ className = 'w-5 h-5 text-blue-500' } = {}) {
  return (
    <svg className={className} fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24">
      <path d="M18 6L6 18M9 3v4M15 3v4M3 9h4M3 15h4M14 14l3 3-2 2-3-3M10 10L7 7l2-2 3 3" />
    </svg>
  )
}

function IconClock() {
  return (
    <svg className="w-3 h-3 shrink-0 text-gray-300" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24">
      <circle cx="12" cy="12" r="10" /><path d="M12 6v6l4 2" />
    </svg>
  )
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function timeAgo(iso: string | null): string {
  if (!iso) return 'never'
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

// ── Connection Form Modal ─────────────────────────────────────────────────────

type FormState = Omit<ConnectionCreate, never>

const EMPTY_FORM: FormState = { name: '', url: '', database: '', username: '', credential: '', credential_type: 'api_key' }

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2 mb-2">
      <span className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">{children}</span>
      <div className="flex-1 h-px bg-gray-100" />
    </div>
  )
}

function InputWithIcon({
  icon,
  label,
  hint,
  type = 'text',
  placeholder,
  value,
  required,
  onChange,
  suffix,
}: {
  icon: React.ReactNode
  label: string
  hint?: string
  type?: string
  placeholder?: string
  value: string
  required?: boolean
  onChange: (v: string) => void
  suffix?: React.ReactNode
}) {
  return (
    <div>
      <label className="block text-xs font-semibold text-gray-600 mb-1">{label}</label>
      <div className="flex items-center gap-0 border border-gray-200 rounded-xl bg-gray-50 focus-within:bg-white focus-within:border-blue-400 focus-within:ring-2 focus-within:ring-blue-100 transition-all">
        <span className="pl-3 pr-2 flex items-center">{icon}</span>
        <input
          type={type}
          required={required}
          placeholder={placeholder}
          value={value}
          onChange={e => onChange(e.target.value)}
          className="flex-1 bg-transparent py-2.5 pr-3 text-sm text-gray-800 placeholder:text-gray-300 outline-none min-w-0"
        />
        {suffix && <span className="pr-2">{suffix}</span>}
      </div>
      {hint && <p className="mt-1 text-[11px] text-gray-400">{hint}</p>}
    </div>
  )
}


function ConnectionFormModal({
  editConn,
  onClose,
  onSaved,
}: {
  editConn: Connection | null
  onClose: () => void
  onSaved: () => void
}) {
  const [form, setForm] = useState<FormState>(
    editConn
      ? { name: editConn.name, url: editConn.url, database: editConn.database, username: editConn.username, credential: '', credential_type: editConn.credential_type }
      : EMPTY_FORM
  )
  const [saving, setSaving] = useState(false)
  const [showSecret, setShowSecret] = useState(false)
  const [error, setError] = useState('')
  const firstRef = useRef<HTMLInputElement>(null)

  useEffect(() => { firstRef.current?.focus() }, [])

  const set = (k: keyof FormState) => (v: string) => setForm(f => ({ ...f, [k]: v }))

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    setError('')
    try {
      if (editConn) {
        const update: Partial<ConnectionCreate> = { ...form }
        if (!update.credential) delete update.credential
        await api.connections.update(editConn.id, update)
      } else {
        await api.connections.create(form)
      }
      onSaved()
      onClose()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md overflow-hidden">

        {/* Modal header */}
        <div className="bg-gradient-to-r from-blue-600 to-indigo-600 px-6 py-5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-xl bg-white/20 flex items-center justify-center">
                <IconPlug className="w-5 h-5 text-white" />
              </div>
              <div>
                <h3 className="text-base font-bold text-white">
                  {editConn ? 'Edit Connection' : 'New Connection'}
                </h3>
                <p className="text-xs text-blue-200 mt-0.5">
                  {editConn ? `Editing "${editConn.name}"` : 'Connect to an Odoo instance'}
                </p>
              </div>
            </div>
            <button onClick={onClose} className="text-white/70 hover:text-white transition-colors">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path d="M18 6 6 18M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        {/* Form body */}
        <form onSubmit={submit} className="px-6 py-5 space-y-5 max-h-[75vh] overflow-y-auto">

          {error && (
            <div className="flex items-center gap-2 p-3 bg-red-50 border border-red-200 rounded-xl text-red-600 text-xs">
              <span className="text-red-400">⚠</span> {error}
            </div>
          )}

          {/* Identity */}
          <div>
            <SectionLabel>Identity</SectionLabel>
            <InputWithIcon
              icon={<IconTag className="w-4 h-4 text-gray-400" />}
              label="Connection Name"
              placeholder="e.g. Production, Staging"
              value={form.name}
              required
              onChange={set('name')}
            />
          </div>

          {/* Server */}
          <div className="space-y-3">
            <SectionLabel>Server</SectionLabel>
            <InputWithIcon
              icon={<IconGlobe className="w-4 h-4 text-gray-400" />}
              label="Odoo URL"
              placeholder="https://your-odoo.com"
              hint="Include the protocol. Trailing slashes are stripped."
              value={form.url}
              required
              onChange={set('url')}
            />
            <InputWithIcon
              icon={<IconDatabase className="w-4 h-4 text-gray-400" />}
              label="Database"
              placeholder="your_database_name"
              value={form.database}
              required
              onChange={set('database')}
            />
          </div>

          {/* Auth */}
          <div className="space-y-3">
            <SectionLabel>Authentication</SectionLabel>
            <InputWithIcon
              icon={<IconUser className="w-4 h-4 text-gray-400" />}
              label="Username"
              placeholder="admin"
              value={form.username}
              required
              onChange={set('username')}
            />

            <InputWithIcon
              icon={<IconKey className="w-4 h-4 text-gray-400" />}
              label={`Credential${editConn ? ' — leave blank to keep current' : ''}`}
              placeholder="API key or password"
              type={showSecret ? 'text' : 'password'}
              value={form.credential}
              required={!editConn}
              onChange={set('credential')}
              suffix={
                <button
                  type="button"
                  onClick={() => setShowSecret(s => !s)}
                  className="text-gray-400 hover:text-gray-600 transition-colors"
                  tabIndex={-1}
                >
                  <IconEye open={showSecret} />
                </button>
              }
            />
          </div>
        </form>

        {/* Footer */}
        <div className="px-6 py-4 bg-gray-50 border-t border-gray-100 flex items-center justify-between">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-sm rounded-xl border border-gray-200 text-gray-600 hover:bg-white transition-colors"
          >
            Cancel
          </button>
          <button
            type="submit"
            form=""
            onClick={e => { e.preventDefault(); const form = (e.target as HTMLElement).closest('.fixed')?.querySelector('form'); form?.requestSubmit() }}
            disabled={saving}
            className="flex items-center gap-2 px-5 py-2 text-sm font-semibold rounded-xl bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 shadow-sm shadow-blue-200 transition-all"
          >
            {saving ? (
              <>
                <svg className="w-3.5 h-3.5 animate-spin" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.37 0 0 5.37 0 12h4z"/>
                </svg>
                Saving…
              </>
            ) : (
              <>{editConn ? 'Save Changes' : 'Add Connection'}</>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Kanban Card ───────────────────────────────────────────────────────────────

function ConnectionCard({
  conn,
  testing,
  activating,
  onTest,
  onActivate,
  onEdit,
  onDelete,
}: {
  conn: Connection
  testing: boolean
  activating: boolean
  onTest: () => void
  onActivate: () => void
  onEdit: () => void
  onDelete: () => void
}) {
  const isActive = conn.is_active
  const borderClass = isActive
    ? 'border-blue-400 shadow-blue-100 shadow-md'
    : 'border-gray-200 hover:border-gray-300 hover:shadow-sm'

  return (
    <div className={`relative flex flex-col bg-white rounded-2xl border transition-all duration-200 ${borderClass}`}>
      {/* Top stripe for active */}
      {isActive && <div className="h-1 rounded-t-2xl bg-gradient-to-r from-blue-500 to-indigo-500" />}

      {/* Card header */}
      <div className="flex items-start justify-between px-5 pt-4 pb-2">
        <div className="flex items-center gap-2 min-w-0">
          {isActive && (
            <span className="inline-flex items-center gap-1 bg-blue-50 text-blue-600 text-[10px] font-semibold px-2 py-0.5 rounded-full border border-blue-200">
              <span className="w-1.5 h-1.5 rounded-full bg-blue-500 inline-block" />
              ACTIVE
            </span>
          )}
        </div>
        <StatusDot status={conn.status} />
      </div>

      {/* Name */}
      <div className="px-5 pb-3">
        <h3 className="text-base font-semibold text-gray-900 leading-tight truncate">{conn.name}</h3>
        <p className="text-[10px] font-medium text-gray-400 uppercase tracking-wide mt-0.5">
          {STATUS_LABEL[conn.status] ?? conn.status}
          {conn.last_tested_at && (
            <span className="normal-case tracking-normal font-normal text-gray-300"> · tested {timeAgo(conn.last_tested_at)}</span>
          )}
        </p>
      </div>

      {/* Divider */}
      <div className="mx-5 border-t border-gray-100" />

      {/* Metadata */}
      <div className="px-5 py-3 space-y-1.5 flex-1">
        <div className="flex items-center gap-2">
          <IconGlobe />
          <span className="text-xs text-gray-500 truncate">{conn.url}</span>
        </div>
        <div className="flex items-center gap-2">
          <IconDatabase />
          <span className="text-xs text-gray-500 truncate">{conn.database}</span>
        </div>
        <div className="flex items-center gap-2">
          <IconUser />
          <span className="text-xs text-gray-500 truncate">{conn.username}</span>
        </div>
        <div className="flex items-center gap-2">
          <IconKey />
          <span className="text-xs text-gray-400">{conn.credential_type === 'api_key' ? 'API Key' : 'Password'}</span>
        </div>

        {conn.last_error && (
          <div className="mt-2 flex items-start gap-1.5 bg-red-50 border border-red-100 rounded-lg px-2.5 py-1.5">
            <span className="text-red-400 text-xs mt-0.5">⚠</span>
            <span className="text-xs text-red-600 line-clamp-2">{conn.last_error}</span>
          </div>
        )}
      </div>

      {/* Footer actions */}
      <div className="px-4 py-3 border-t border-gray-100 flex items-center justify-between gap-2">
        <div className="flex items-center gap-1 text-[10px] text-gray-300">
          <IconClock />
          <span>Added {timeAgo(conn.created_at)}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <button
            onClick={onTest}
            disabled={testing}
            className="text-xs px-2.5 py-1 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-40 transition-colors"
          >
            {testing ? '…' : 'Test'}
          </button>
          {!isActive && (
            <button
              onClick={onActivate}
              disabled={activating}
              className="text-xs px-2.5 py-1 rounded-lg border border-green-200 text-green-700 hover:bg-green-50 disabled:opacity-40 transition-colors"
            >
              {activating ? '…' : 'Activate'}
            </button>
          )}
          <button
            onClick={onEdit}
            className="text-xs px-2.5 py-1 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 transition-colors"
          >
            Edit
          </button>
          <button
            onClick={onDelete}
            className="text-xs px-2.5 py-1 rounded-lg border border-red-100 text-red-500 hover:bg-red-50 transition-colors"
          >
            Delete
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function Connections() {
  const [conns, setConns] = useState<Connection[]>([])
  const [showModal, setShowModal] = useState(false)
  const [editConn, setEditConn] = useState<Connection | null>(null)
  const [testing, setTesting] = useState<number | null>(null)
  const [activating, setActivating] = useState<number | null>(null)
  const [listError, setListError] = useState('')

  function load() {
    api.connections.list().then(setConns).catch(e => setListError(e.message))
  }

  useEffect(() => { load() }, [])

  function openAdd() { setEditConn(null); setShowModal(true) }
  function openEdit(c: Connection) { setEditConn(c); setShowModal(true) }

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
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-bold text-gray-900">Odoo Connections</h2>
          <p className="text-sm text-gray-400 mt-0.5">
            {conns.length} connection{conns.length !== 1 ? 's' : ''} · {conns.filter(c => c.is_active).length} active
          </p>
        </div>
        <button
          onClick={openAdd}
          className="flex items-center gap-1.5 bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors shadow-sm"
        >
          <span className="text-lg leading-none">+</span> Add Connection
        </button>
      </div>

      {listError && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
          {listError}
        </div>
      )}

      {/* Legend */}
      {conns.length > 0 && (
        <div className="flex items-center gap-4 mb-5 text-xs text-gray-400">
          <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-green-400 inline-block" />Connected</span>
          <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-red-500 inline-block" />Error</span>
          <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-gray-300 inline-block" />Untested</span>
        </div>
      )}

      {/* Kanban grid */}
      {conns.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <div className="w-16 h-16 rounded-full bg-gray-100 flex items-center justify-center mb-4">
            <IconDatabase className="w-7 h-7 text-gray-400" />
          </div>
          <p className="text-gray-500 font-medium">No connections yet</p>
          <p className="text-gray-400 text-sm mt-1">Add an Odoo connection to get started</p>
          <button
            onClick={openAdd}
            className="mt-4 bg-blue-600 text-white px-5 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 transition-colors"
          >
            + Add Connection
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {conns.map(c => (
            <ConnectionCard
              key={c.id}
              conn={c}
              testing={testing === c.id}
              activating={activating === c.id}
              onTest={() => testConn(c.id)}
              onActivate={() => activateConn(c.id)}
              onEdit={() => openEdit(c)}
              onDelete={() => deleteConn(c.id)}
            />
          ))}
        </div>
      )}

      {/* Modal */}
      {showModal && (
        <ConnectionFormModal
          editConn={editConn}
          onClose={() => setShowModal(false)}
          onSaved={load}
        />
      )}
    </div>
  )
}
