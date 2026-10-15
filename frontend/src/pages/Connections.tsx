import { useEffect, useState, useRef } from 'react'
import { api, type ApiMode, type Connection, type ConnectionCreate, type TransportMode } from '../lib/api'

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

function IconClock({ className = 'w-3 h-3 shrink-0 text-gray-300' } = {}) {
  return (
    <svg className={className} fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24">
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

const MODE_LABEL: Record<TransportMode, string> = { json2: 'JSON-2', xmlrpc: 'XML-RPC' }

/** "20.0+e-20260926" → "20.0", "saas~18.4+e" → "saas~18.4" */
function shortVersion(raw: string | null): string | null {
  if (!raw) return null
  return raw.split('+')[0] || raw
}

/** Major version number of a raw Odoo version string, or null. */
function majorVersion(raw: string | null): number | null {
  const m = raw ? /(\d+)/.exec(raw) : null
  return m ? parseInt(m[1], 10) : null
}

function capitalize(s: string): string {
  return s ? s[0].toUpperCase() + s.slice(1) : s
}

// ── Connection Form Modal ─────────────────────────────────────────────────────

type CredentialType = ConnectionCreate['credential_type']

interface FormState {
  name: string
  url: string
  database: string
  username: string
  credential: string
  credential_type: CredentialType
  api_mode: ApiMode
  verify_ssl: boolean
  /** Kept as text while typing; validated on submit. */
  timeout: string
  /** Raw JSON text; validated on submit. */
  default_context: string
}

const EMPTY_FORM: FormState = {
  name: '',
  url: '',
  database: '',
  username: '',
  credential: '',
  credential_type: 'api_key',
  api_mode: 'auto',
  verify_ssl: true,
  timeout: '120',
  default_context: '',
}

function formFromConnection(c: Connection): FormState {
  const ctx = c.default_context ?? {}
  return {
    name: c.name,
    url: c.url,
    database: c.database,
    username: c.username,
    credential: '',
    credential_type: c.credential_type,
    api_mode: c.api_mode ?? 'auto',
    verify_ssl: c.verify_ssl ?? true,
    timeout: String(c.timeout ?? 120),
    default_context: Object.keys(ctx).length > 0 ? JSON.stringify(ctx, null, 2) : '',
  }
}

const API_MODE_HINT: Record<ApiMode, string> = {
  auto: 'Auto uses JSON-2 on Odoo 19+ and XML-RPC on 18 and older.',
  xmlrpc: 'Always XML-RPC. Works on every version, but it is deprecated on Odoo 19+.',
  json2: 'Always JSON-2. Needs Odoo 19+ and an API key with RPC scope (passwords are rejected).',
}

const TIMEOUT_MIN = 5
const TIMEOUT_MAX = 900

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
  min,
  max,
  error,
}: {
  icon: React.ReactNode
  label: string
  hint?: React.ReactNode
  type?: string
  placeholder?: string
  value: string
  required?: boolean
  onChange: (v: string) => void
  suffix?: React.ReactNode
  min?: number
  max?: number
  error?: string
}) {
  return (
    <div>
      <label className="block text-xs font-semibold text-gray-600 mb-1">{label}</label>
      <div className={`flex items-center gap-0 border rounded-xl bg-gray-50 focus-within:bg-white focus-within:ring-2 transition-all ${
        error
          ? 'border-red-300 focus-within:border-red-400 focus-within:ring-red-100'
          : 'border-gray-200 focus-within:border-blue-400 focus-within:ring-blue-100'
      }`}>
        <span className="pl-3 pr-2 flex items-center">{icon}</span>
        <input
          type={type}
          required={required}
          placeholder={placeholder}
          value={value}
          min={min}
          max={max}
          onChange={e => onChange(e.target.value)}
          className="flex-1 bg-transparent py-2.5 pr-3 text-sm text-gray-800 placeholder:text-gray-300 outline-none min-w-0"
        />
        {suffix && <span className="pr-2">{suffix}</span>}
      </div>
      {error && <p className="mt-1 text-[11px] text-red-600">{error}</p>}
      {hint && !error && <p className="mt-1 text-[11px] text-gray-400">{hint}</p>}
    </div>
  )
}

function Segmented<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T
  options: { value: T; label: string; sub?: string }[]
  onChange: (v: T) => void
}) {
  return (
    <div className="flex gap-1 p-1 bg-gray-100 rounded-xl">
      {options.map(o => {
        const selected = o.value === value
        return (
          <button
            key={o.value}
            type="button"
            aria-pressed={selected}
            onClick={() => onChange(o.value)}
            className={`flex-1 px-2 py-1.5 rounded-lg text-xs font-semibold transition-all ${
              selected ? 'bg-white text-blue-600 shadow-sm' : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            {o.label}
            {o.sub && (
              <span className={`block text-[10px] font-normal ${selected ? 'text-blue-400' : 'text-gray-400'}`}>
                {o.sub}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}

function Toggle({
  label,
  checked,
  onChange,
  onText,
  offText,
}: {
  label: string
  checked: boolean
  onChange: (v: boolean) => void
  onText: string
  offText: string
}) {
  return (
    <div>
      <label className="block text-xs font-semibold text-gray-600 mb-1">{label}</label>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        onClick={() => onChange(!checked)}
        className="w-full flex items-center gap-2.5 border border-gray-200 rounded-xl bg-gray-50 px-3 py-2.5 hover:bg-white focus:outline-none focus-visible:border-blue-400 focus-visible:ring-2 focus-visible:ring-blue-100 transition-all"
      >
        <span className={`relative inline-flex h-5 w-9 shrink-0 rounded-full transition-colors ${checked ? 'bg-blue-600' : 'bg-gray-300'}`}>
          <span className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform ${checked ? 'translate-x-4' : ''}`} />
        </span>
        <span className={`text-sm ${checked ? 'text-gray-800' : 'text-amber-600'}`}>{checked ? onText : offText}</span>
      </button>
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
  const [form, setForm] = useState<FormState>(editConn ? formFromConnection(editConn) : EMPTY_FORM)
  const [saving, setSaving] = useState(false)
  const [showSecret, setShowSecret] = useState(false)
  const [error, setError] = useState('')
  const [contextError, setContextError] = useState('')
  const [timeoutError, setTimeoutError] = useState('')
  const firstRef = useRef<HTMLInputElement>(null)

  useEffect(() => { firstRef.current?.focus() }, [])

  const setField = <K extends keyof FormState>(k: K, v: FormState[K]) => setForm(f => ({ ...f, [k]: v }))
  const set = (k: 'name' | 'url' | 'database' | 'username' | 'credential') => (v: string) => setField(k, v)

  /** Empty → null; a JSON object → that object; anything else → error string. */
  function parseContext(raw: string): { value: Record<string, unknown> | null; error?: string } {
    const text = raw.trim()
    if (!text) return { value: null }
    let parsed: unknown
    try {
      parsed = JSON.parse(text)
    } catch (err) {
      return { value: null, error: `Invalid JSON: ${err instanceof Error ? err.message : 'parse error'}` }
    }
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return { value: null, error: 'Default context must be a JSON object, e.g. {"lang": "en_US"}.' }
    }
    return { value: parsed as Record<string, unknown> }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setError('')

    const ctx = parseContext(form.default_context)
    setContextError(ctx.error ?? '')
    const timeout = Number(form.timeout)
    const timeoutOk = form.timeout.trim() !== '' && Number.isInteger(timeout) && timeout >= TIMEOUT_MIN && timeout <= TIMEOUT_MAX
    setTimeoutError(timeoutOk ? '' : `Enter a whole number of seconds between ${TIMEOUT_MIN} and ${TIMEOUT_MAX}.`)
    if (ctx.error || !timeoutOk) return

    const payload: ConnectionCreate = {
      name: form.name,
      url: form.url,
      database: form.database,
      username: form.username,
      credential: form.credential,
      credential_type: form.credential_type,
      api_mode: form.api_mode,
      verify_ssl: form.verify_ssl,
      timeout,
      default_context: ctx.value,
    }

    setSaving(true)
    try {
      if (editConn) {
        // {} clears the stored context; omitting the credential keeps the current one
        const update: Partial<ConnectionCreate> = { ...payload, default_context: ctx.value ?? {} }
        if (!update.credential) delete update.credential
        await api.connections.update(editConn.id, update)
      } else {
        await api.connections.create(payload)
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
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg overflow-hidden">

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

            <div>
              <label className="block text-xs font-semibold text-gray-600 mb-1">Credential type</label>
              <Segmented<CredentialType>
                value={form.credential_type}
                onChange={v => setField('credential_type', v)}
                options={[
                  { value: 'api_key', label: 'API key' },
                  { value: 'password', label: 'Password' },
                ]}
              />
            </div>

            <InputWithIcon
              icon={<IconKey className="w-4 h-4 text-gray-400" />}
              label={`${form.credential_type === 'api_key' ? 'API Key' : 'Password'}${editConn ? ' — leave blank to keep current' : ''}`}
              placeholder={form.credential_type === 'api_key' ? 'Odoo API key' : 'Odoo password'}
              hint={
                <>
                  Odoo 19+ needs an API key with RPC scope: Odoo → avatar → Preferences → Account Security → New API Key.
                  {form.credential_type === 'password' && (
                    <span className="block mt-0.5 text-amber-600">
                      A password only works over XML-RPC, which is deprecated on Odoo 19+.
                    </span>
                  )}
                </>
              }
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

          {/* Transport */}
          <div className="space-y-3">
            <SectionLabel>Transport</SectionLabel>
            <div>
              <label className="block text-xs font-semibold text-gray-600 mb-1">API mode</label>
              <Segmented<ApiMode>
                value={form.api_mode}
                onChange={v => setField('api_mode', v)}
                options={[
                  { value: 'auto', label: 'Auto', sub: 'recommended' },
                  { value: 'xmlrpc', label: 'XML-RPC', sub: 'Odoo ≤ 18' },
                  { value: 'json2', label: 'JSON-2', sub: 'Odoo 19+' },
                ]}
              />
              <p className="mt-1 text-[11px] text-gray-400">{API_MODE_HINT[form.api_mode]}</p>
              {form.api_mode === 'json2' && form.credential_type === 'password' && (
                <p className="mt-0.5 text-[11px] text-amber-600">JSON-2 does not accept passwords: switch the credential to an API key.</p>
              )}
            </div>

            <div className="grid grid-cols-2 gap-3">
              <Toggle
                label="SSL certificate"
                checked={form.verify_ssl}
                onChange={v => setField('verify_ssl', v)}
                onText="Verify"
                offText="Don't verify"
              />
              <InputWithIcon
                icon={<IconClock className="w-4 h-4 text-gray-400" />}
                label="Timeout"
                type="number"
                min={TIMEOUT_MIN}
                max={TIMEOUT_MAX}
                value={form.timeout}
                required
                error={timeoutError}
                onChange={v => { setField('timeout', v); setTimeoutError('') }}
                suffix={<span className="text-xs text-gray-400">sec</span>}
              />
            </div>
            <p className="-mt-1 text-[11px] text-gray-400">
              Turn SSL verification off only for self-signed certificates on a trusted network. Timeout applies to each Odoo call ({TIMEOUT_MIN}–{TIMEOUT_MAX} s).
            </p>

            <div>
              <label className="block text-xs font-semibold text-gray-600 mb-1">Default context</label>
              <textarea
                rows={Math.min(8, Math.max(3, form.default_context.split('\n').length))}
                spellCheck={false}
                placeholder={'{"lang": "en_US"}'}
                value={form.default_context}
                onChange={e => { setField('default_context', e.target.value); setContextError('') }}
                className={`w-full border rounded-xl bg-gray-50 px-3 py-2.5 text-sm font-mono text-gray-800 placeholder:text-gray-300 outline-none focus:bg-white focus:ring-2 transition-all resize-y ${
                  contextError
                    ? 'border-red-300 focus:border-red-400 focus:ring-red-100'
                    : 'border-gray-200 focus:border-blue-400 focus:ring-blue-100'
                }`}
              />
              {contextError ? (
                <p className="mt-1 text-[11px] text-red-600">{contextError}</p>
              ) : (
                <p className="mt-1 text-[11px] text-gray-400">
                  JSON object added to the context of every Odoo call (e.g. lang, tz, allowed_company_ids). Leave empty for none.
                </p>
              )}
            </div>
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

const BADGE = 'inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full border'

function TransportBadges({ conn }: { conn: Connection }) {
  const version = shortVersion(conn.detected_version)
  const modeClass =
    conn.detected_mode === 'json2'
      ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
      : conn.detected_mode === 'xmlrpc'
        ? 'bg-slate-50 text-slate-600 border-slate-200'
        : 'bg-gray-50 text-gray-500 border-gray-200'
  return (
    <div className="flex flex-wrap items-center gap-1.5 mt-2">
      {version ? (
        <span className={`${BADGE} ${modeClass}`} title={`Odoo ${conn.detected_version}`}>
          Odoo {version}
          {conn.detected_mode && <> · {MODE_LABEL[conn.detected_mode]}</>}
        </span>
      ) : (
        <span className="text-[11px] text-gray-400 italic">Version not detected yet — click Test</span>
      )}
      {conn.api_mode && conn.api_mode !== 'auto' && (
        <span className={`${BADGE} bg-violet-50 text-violet-700 border-violet-200`} title="API mode is not auto">
          forced {MODE_LABEL[conn.api_mode]}
        </span>
      )}
      {conn.verify_ssl === false && (
        <span className={`${BADGE} bg-amber-50 text-amber-700 border-amber-200`} title="SSL certificate is not verified">
          SSL not verified
        </span>
      )}
    </div>
  )
}

function TestSteps({ conn }: { conn: Connection }) {
  const steps = conn.last_test_steps ?? []
  if (steps.length === 0) return null
  // Editing a connection resets its status to untested; the steps then describe the old settings.
  const stale = conn.status === 'untested'
  const failed = steps.some(st => !st.ok)
  return (
    <div
      className={`mt-2 rounded-lg border px-2.5 py-2 ${failed ? 'border-red-100 bg-red-50/50' : 'border-gray-100 bg-gray-50'} ${stale ? 'opacity-60' : ''}`}
      title={failed ? conn.last_error ?? undefined : undefined}
    >
      <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest mb-1">
        Last test
        {stale && <span className="normal-case tracking-normal font-normal"> · settings changed since</span>}
      </p>
      <ul className="space-y-0.5">
        {steps.map((st, i) => (
          <li key={i} className="flex items-start gap-1.5 text-[11px] leading-snug">
            <span className={`shrink-0 w-3 font-bold ${st.ok ? 'text-green-500' : 'text-red-500'}`}>{st.ok ? '✓' : '✗'}</span>
            <span className="shrink-0 w-[6.75rem] text-gray-500">{capitalize(st.step)}</span>
            <span
              className={`min-w-0 flex-1 ${st.ok ? 'text-gray-400 truncate' : 'text-red-600 break-words'}`}
              title={st.detail}
            >
              {st.detail}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

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
  const major = majorVersion(conn.detected_version)
  const usesDeprecatedXmlrpc = major !== null && major >= 19 && conn.credential_type === 'password'
  const hasFailedStep = (conn.last_test_steps ?? []).some(st => !st.ok)
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
        <TransportBadges conn={conn} />
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

        {usesDeprecatedXmlrpc && (
          <div className="mt-2 flex items-start gap-1.5 bg-amber-50 border border-amber-200 rounded-lg px-2.5 py-1.5">
            <span className="text-amber-500 text-xs mt-0.5">⚠</span>
            <span className="text-xs text-amber-700">
              Using XML-RPC (deprecated): switch to an API key with RPC scope to use JSON-2.
            </span>
          </div>
        )}

        {/* Summary line; skipped when a failed test step below already shows the error */}
        {conn.last_error && !hasFailedStep && (
          <div className="mt-2 flex items-start gap-1.5 bg-red-50 border border-red-100 rounded-lg px-2.5 py-1.5" title={conn.last_error}>
            <span className="text-red-400 text-xs mt-0.5">⚠</span>
            <span className="text-xs text-red-600 line-clamp-2">{conn.last_error}</span>
          </div>
        )}

        <TestSteps conn={conn} />
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
    setListError('')
    try {
      const updated = await api.connections.test(id)
      setConns(prev => prev.map(c => (c.id === id ? updated : c)))
    } catch (e: unknown) {
      setListError(e instanceof Error ? e.message : 'Test failed')
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
