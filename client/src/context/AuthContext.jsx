import { createContext, useContext, useEffect, useState, useCallback, useMemo } from 'react'
import { getToken, setToken, getMe, loginRequest, registerRequest, acceptInvite as acceptInviteRequest } from '../api'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [status, setStatus] = useState('loading') // loading | authenticated | anonymous
  const [user, setUser] = useState(null)

  // On mount, validate any stored token against the backend instead of just
  // trusting it — it may have expired or been signed by a since-restarted
  // backend process (see auth.py's per-process JWT_SECRET fallback).
  useEffect(() => {
    if (!getToken()) {
      setStatus('anonymous')
      return
    }
    getMe()
      .then((u) => {
        setUser(u)
        setStatus('authenticated')
      })
      .catch(() => {
        setToken(null)
        setUser(null)
        setStatus('anonymous')
      })
  }, [])

  // api.js's request() fires this on any 401 other than a login/register
  // attempt itself, so an expired/invalid session is never silently stuck.
  useEffect(() => {
    const onUnauthorized = () => {
      setUser(null)
      setStatus('anonymous')
    }
    window.addEventListener('phc:unauthorized', onUnauthorized)
    return () => window.removeEventListener('phc:unauthorized', onUnauthorized)
  }, [])

  // Shared by login/register/acceptInvite — all three return the same
  // {token, user} shape and all three mean "log the user in".
  const applyAuthResponse = useCallback((data) => {
    setToken(data.token)
    setUser(data.user)
    setStatus('authenticated')
  }, [])

  const login = useCallback(
    async (email, password) => applyAuthResponse(await loginRequest(email, password)),
    [applyAuthResponse]
  )

  const register = useCallback(
    async (name, email, password) => applyAuthResponse(await registerRequest(name, email, password)),
    [applyAuthResponse]
  )

  const acceptInvite = useCallback(
    async (token, name, password) => applyAuthResponse(await acceptInviteRequest(token, name, password)),
    [applyAuthResponse]
  )

  const logout = useCallback(() => {
    setToken(null)
    setUser(null)
    setStatus('anonymous')
  }, [])

  const value = useMemo(
    () => ({ status, user, login, register, acceptInvite, logout }),
    [status, user, login, register, acceptInvite, logout]
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return ctx
}
