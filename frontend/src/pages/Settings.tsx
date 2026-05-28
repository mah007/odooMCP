import { useEffect, useState } from 'react'
import { api, type AdminRow } from '../lib/api'
import { currentUsername } from '../lib/auth'

// ── Icons ─────────────────────────────────────────────────────────────────────

function IconShield() {
  return (
    <svg className="w-5 h-5 text-blue-500" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
    </svg>
  )
}

function IconUsers() {
  return (
    <svg className="w-5 h-5 text-indigo-500" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24">
      <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" />
      <path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" />
    </svg>
  )
}

function IconUser() {
  return (
    <svg className="w-4 h-4 text-gray-400" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24">
      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" />
    </svg>
  )
}

function IconLock() {
  return (
    <svg className="w-4 h-4 text-gray-400" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24">
      <rect x="3" y="11" width="18" height="11" rx="2" ry="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" />
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
      <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
      <line x1="1" y1="1" x2="23" y2="23" />
    </svg>
  )
}

function IconTrash() {
  return (
    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24">
      <polyline points="3 6 5 6 21 6" /><path d="M19 6l-1 14H6L5 6" /><path d="M10 11v6M14 11v6" /><path d="M9 6V4h6v2" />
    </svg>
  )
}

function IconPlus() {
  return (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
      <line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" />
    </svg>
  )
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function timeAgo(iso: string | null): string {
  if (!iso) return 'unknown'
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

// ── Input with icon ───────────────────────────────────────────────────────────

function InputIcon({
  icon, label, type = 'text', placeholder, value, onChange, suffix, required,
}: {
  icon: React.ReactNode
  label: string
  type?: string
  placeholder?: string
  value: string
  onChange: (v: string) => void
  suffix?: React.ReactNode
  required?: boolean
}) {
  return (
    <div>
      <label className="block text-xs font-semibold text-gray-600 mb-1">{label}</label>
      <div className="flex items-center border border-gray-200 rounded-xl bg-gray-50 focus-within:bg-white focus-within:border-blue-400 focus-within:ring-2 focus-within:ring-blue-100 transition-all">
        <span className="pl-3 pr-2">{icon}</span>
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
    </div>
  )
}

// ── Change Password Card ──────────────────────────────────────────────────────

function ChangePasswordCard() {
  const [form, setForm] = useState({ current: '', next: '', confirm: '' })
  const [show, setShow] = useState(false)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState<{ type: 'ok' | 'err'; text: string } | null>(null)
  const me = currentUsername()

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (form.next !== form.confirm) {
      setMsg({ type: 'err', text: 'New passwords do not match' })
      return
    }
    if (form.next.length < 8) {
      setMsg({ type: 'err', text: 'Password must be at least 8 characters' })
      return
    }
    setSaving(true)
    setMsg(null)
    try {
      await api.admins.changePassword(form.current, form.next)
      setMsg({ type: 'ok', text: 'Password updated successfully' })
      setForm({ current: '', next: '', confirm: '' })
    } catch (err: unknown) {
      setMsg({ type: 'err', text: err instanceof Error ? err.message : 'Failed' })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-3 px-6 py-4 border-b border-gray-100">
        <div className="w-9 h-9 rounded-xl bg-blue-50 flex items-center justify-center">
          <IconShield />
        </div>
        <div>
          <h3 className="text-sm font-bold text-gray-900">My Profile</h3>
          <p className="text-xs text-gray-400 mt-0.5">Signed in as <span className="font-semibold text-gray-600">{me}</span></p>
        </div>
      </div>

      {/* Avatar + name banner */}
      <div className="px-6 py-5 flex items-center gap-4 bg-gradient-to-r from-blue-50 to-indigo-50 border-b border-gray-100">
        <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center shadow-sm">
          <span className="text-xl font-bold text-white">{me.charAt(0).toUpperCase()}</span>
        </div>
        <div>
          <p className="text-base font-bold text-gray-900">{me}</p>
          <span className="inline-flex items-center gap-1 mt-1 bg-blue-100 text-blue-700 text-[10px] font-bold px-2 py-0.5 rounded-full">
            <span className="w-1.5 h-1.5 rounded-full bg-blue-500 inline-block" /> ADMIN
          </span>
        </div>
      </div>

      {/* Change password form */}
      <form onSubmit={submit} className="px-6 py-5 space-y-3">
        <p className="text-xs font-bold text-gray-500 uppercase tracking-widest mb-1">Change Password</p>

        {msg && (
          <div className={`flex items-center gap-2 px-3 py-2.5 rounded-xl text-xs ${
            msg.type === 'ok' ? 'bg-green-50 border border-green-200 text-green-700' : 'bg-red-50 border border-red-200 text-red-600'
          }`}>
            <span>{msg.type === 'ok' ? '✓' : '⚠'}</span> {msg.text}
          </div>
        )}

        <InputIcon
          icon={<IconLock />}
          label="Current Password"
          type={show ? 'text' : 'password'}
          placeholder="Enter current password"
          value={form.current}
          required
          onChange={v => setForm(f => ({ ...f, current: v }))}
        />
        <InputIcon
          icon={<IconLock />}
          label="New Password"
          type={show ? 'text' : 'password'}
          placeholder="At least 8 characters"
          value={form.next}
          required
          onChange={v => setForm(f => ({ ...f, next: v }))}
        />
        <InputIcon
          icon={<IconLock />}
          label="Confirm New Password"
          type={show ? 'text' : 'password'}
          placeholder="Repeat new password"
          value={form.confirm}
          required
          onChange={v => setForm(f => ({ ...f, confirm: v }))}
          suffix={
            <button type="button" onClick={() => setShow(s => !s)} className="text-gray-400 hover:text-gray-600 transition-colors" tabIndex={-1}>
              <IconEye open={show} />
            </button>
          }
        />

        <div className="pt-1 flex justify-end">
          <button
            type="submit"
            disabled={saving}
            className="flex items-center gap-2 px-5 py-2 text-sm font-semibold rounded-xl bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 shadow-sm transition-all"
          >
            {saving ? (
              <>
                <svg className="w-3.5 h-3.5 animate-spin" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.37 0 0 5.37 0 12h4z"/>
                </svg>
                Saving…
              </>
            ) : 'Update Password'}
          </button>
        </div>
      </form>
    </div>
  )
}

// ── Add Admin Modal ───────────────────────────────────────────────────────────

function AddAdminModal({ onClose, onAdded }: { onClose: () => void; onAdded: () => void }) {
  const [form, setForm] = useState({ username: '', password: '', confirm: '' })
  const [show, setShow] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (form.password !== form.confirm) { setError('Passwords do not match'); return }
    setSaving(true)
    setError('')
    try {
      await api.admins.create(form.username, form.password)
      onAdded()
      onClose()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-sm overflow-hidden">
        <div className="bg-gradient-to-r from-indigo-600 to-purple-600 px-6 py-5 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-white/20 flex items-center justify-center">
              <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24">
                <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><line x1="19" y1="8" x2="19" y2="14" /><line x1="22" y1="11" x2="16" y2="11" />
              </svg>
            </div>
            <div>
              <h3 className="text-base font-bold text-white">Add Admin</h3>
              <p className="text-xs text-indigo-200 mt-0.5">Create a new admin account</p>
            </div>
          </div>
          <button onClick={onClose} className="text-white/70 hover:text-white transition-colors">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </button>
        </div>

        <form onSubmit={submit} className="px-6 py-5 space-y-3">
          {error && (
            <div className="flex items-center gap-2 p-3 bg-red-50 border border-red-200 rounded-xl text-red-600 text-xs">
              <span>⚠</span> {error}
            </div>
          )}
          <InputIcon
            icon={<IconUser />}
            label="Username"
            placeholder="e.g. john"
            value={form.username}
            required
            onChange={v => setForm(f => ({ ...f, username: v }))}
          />
          <InputIcon
            icon={<IconLock />}
            label="Password"
            type={show ? 'text' : 'password'}
            placeholder="At least 8 characters"
            value={form.password}
            required
            onChange={v => setForm(f => ({ ...f, password: v }))}
          />
          <InputIcon
            icon={<IconLock />}
            label="Confirm Password"
            type={show ? 'text' : 'password'}
            placeholder="Repeat password"
            value={form.confirm}
            required
            onChange={v => setForm(f => ({ ...f, confirm: v }))}
            suffix={
              <button type="button" onClick={() => setShow(s => !s)} className="text-gray-400 hover:text-gray-600 transition-colors" tabIndex={-1}>
                <IconEye open={show} />
              </button>
            }
          />
        </form>

        <div className="px-6 py-4 bg-gray-50 border-t border-gray-100 flex justify-between">
          <button type="button" onClick={onClose} className="px-4 py-2 text-sm rounded-xl border border-gray-200 text-gray-600 hover:bg-white transition-colors">
            Cancel
          </button>
          <button
            onClick={e => { e.preventDefault(); const form = (e.target as HTMLElement).closest('.fixed')?.querySelector('form'); form?.requestSubmit() }}
            disabled={saving}
            className="flex items-center gap-2 px-5 py-2 text-sm font-semibold rounded-xl bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50 shadow-sm transition-all"
          >
            {saving ? 'Adding…' : 'Add Admin'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Admin List Card ───────────────────────────────────────────────────────────

function AdminListCard() {
  const [admins, setAdmins] = useState<AdminRow[]>([])
  const [showModal, setShowModal] = useState(false)
  const [deleting, setDeleting] = useState<number | null>(null)
  const [error, setError] = useState('')
  const me = currentUsername()

  function load() {
    api.admins.list().then(setAdmins).catch(e => setError(e.message))
  }

  useEffect(() => { load() }, [])

  async function deleteAdmin(id: number, username: string) {
    if (!confirm(`Remove admin "${username}"? This cannot be undone.`)) return
    setDeleting(id)
    try {
      await api.admins.delete(id)
      load()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Delete failed')
    } finally {
      setDeleting(null)
    }
  }

  return (
    <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-indigo-50 flex items-center justify-center">
            <IconUsers />
          </div>
          <div>
            <h3 className="text-sm font-bold text-gray-900">Admin Users</h3>
            <p className="text-xs text-gray-400 mt-0.5">{admins.length} admin{admins.length !== 1 ? 's' : ''} total</p>
          </div>
        </div>
        <button
          onClick={() => setShowModal(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-xl bg-indigo-600 text-white hover:bg-indigo-700 transition-colors shadow-sm"
        >
          <IconPlus /> Add Admin
        </button>
      </div>

      {error && (
        <div className="mx-6 mt-4 p-3 bg-red-50 border border-red-200 rounded-xl text-red-600 text-xs">
          {error}
        </div>
      )}

      {/* Admin rows */}
      <div className="divide-y divide-gray-50">
        {admins.map(admin => {
          const isMe = admin.username === me
          return (
            <div key={admin.id} className="flex items-center gap-3 px-6 py-3.5 hover:bg-gray-50 transition-colors">
              {/* Avatar */}
              <div className={`w-9 h-9 rounded-xl flex items-center justify-center font-bold text-sm shadow-sm ${
                isMe
                  ? 'bg-gradient-to-br from-blue-500 to-indigo-600 text-white'
                  : 'bg-gradient-to-br from-gray-200 to-gray-300 text-gray-600'
              }`}>
                {admin.username.charAt(0).toUpperCase()}
              </div>

              {/* Info */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold text-gray-900">{admin.username}</span>
                  {isMe && (
                    <span className="bg-blue-100 text-blue-600 text-[10px] font-bold px-1.5 py-0.5 rounded-full">YOU</span>
                  )}
                  <span className={`w-1.5 h-1.5 rounded-full inline-block ${admin.is_active ? 'bg-green-400' : 'bg-gray-300'}`} />
                </div>
                <p className="text-xs text-gray-400 mt-0.5">Joined {timeAgo(admin.created_at)}</p>
              </div>

              {/* Delete */}
              {!isMe && (
                <button
                  onClick={() => deleteAdmin(admin.id, admin.username)}
                  disabled={deleting === admin.id}
                  className="flex items-center gap-1 px-2.5 py-1.5 text-xs rounded-lg border border-red-100 text-red-500 hover:bg-red-50 disabled:opacity-40 transition-colors"
                >
                  <IconTrash />
                  {deleting === admin.id ? '…' : 'Remove'}
                </button>
              )}
            </div>
          )
        })}
      </div>

      {showModal && (
        <AddAdminModal onClose={() => setShowModal(false)} onAdded={load} />
      )}
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function Settings() {
  return (
    <div className="p-8 max-w-2xl">
      <div className="mb-6">
        <h2 className="text-xl font-bold text-gray-900">Settings</h2>
        <p className="text-sm text-gray-400 mt-0.5">Manage your profile and admin users</p>
      </div>
      <div className="space-y-6">
        <ChangePasswordCard />
        <AdminListCard />
      </div>
    </div>
  )
}
