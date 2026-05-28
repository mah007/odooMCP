import { useEffect, useState } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import { api } from './lib/api'
import { isLoggedIn } from './lib/auth'
import Setup from './pages/Setup'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Connections from './pages/Connections'
import ApiKeys from './pages/ApiKeys'
import Layout from './components/Layout'

function AppRoutes() {
  const [setupDone, setSetupDone] = useState<boolean | null>(null)
  const navigate = useNavigate()

  useEffect(() => {
    api.auth.status().then(s => {
      setSetupDone(s.setup_done)
      if (!s.setup_done) navigate('/setup')
      else if (!isLoggedIn()) navigate('/login')
    })
  }, [navigate])

  if (setupDone === null) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-50">
        <div className="text-gray-500">Loading…</div>
      </div>
    )
  }

  return (
    <Routes>
      <Route path="/setup" element={<Setup onDone={() => { setSetupDone(true); navigate('/login') }} />} />
      <Route path="/login" element={<Login onDone={() => navigate('/')} />} />
      <Route element={<Layout />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/connections" element={<Connections />} />
        <Route path="/api-keys" element={<ApiKeys />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  )
}
