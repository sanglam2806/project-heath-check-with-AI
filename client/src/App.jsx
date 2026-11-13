import { useEffect, useState } from 'react'
import { AuthProvider, useAuth } from './context/AuthContext'
import { EvaluationProvider } from './context/EvaluationContext'
import { ReEvalJobProvider } from './context/ReEvalJobContext'
import AppShell from './layout/AppShell'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import AcceptInvitePage from './pages/AcceptInvitePage'

function Root() {
  const { status } = useAuth()
  const [hash, setHash] = useState(window.location.hash)

  useEffect(() => {
    const onHashChange = () => setHash(window.location.hash)
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  if (status === 'loading') {
    return <div className="min-h-screen flex items-center justify-center bg-slate-100" />
  }

  if (status !== 'authenticated') {
    const inviteMatch = hash.match(/^#\/accept-invite\/(.+)$/)
    if (inviteMatch) return <AcceptInvitePage token={decodeURIComponent(inviteMatch[1])} />
    return hash === '#/register' ? <RegisterPage /> : <LoginPage />
  }

  return (
    <EvaluationProvider>
      <ReEvalJobProvider>
        <AppShell />
      </ReEvalJobProvider>
    </EvaluationProvider>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <Root />
    </AuthProvider>
  )
}
