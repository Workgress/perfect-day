import { Navigate, Outlet, useLocation } from 'react-router'
import { selectIsAuthenticated, selectIsOnboarded, useSessionStore } from '@/stores/session'
import { paths } from './paths'

export type RedirectState = {
  from?: string
}

export function RequireAuth() {
  const location = useLocation()
  const isAuthenticated = useSessionStore(selectIsAuthenticated)

  if (!isAuthenticated) {
    const state: RedirectState = { from: location.pathname + location.search }
    return <Navigate to={paths.login} replace state={state} />
  }
  return <Outlet />
}

export function RequireOnboarding() {
  const isOnboarded = useSessionStore(selectIsOnboarded)
  return isOnboarded ? <Outlet /> : <Navigate to={paths.onboarding.birthDate} replace />
}

export function GuestOnly() {
  const isAuthenticated = useSessionStore(selectIsAuthenticated)
  return isAuthenticated ? <Navigate to={paths.today} replace /> : <Outlet />
}

export function OnboardingOnly() {
  const isOnboarded = useSessionStore(selectIsOnboarded)
  return isOnboarded ? <Navigate to={paths.today} replace /> : <Outlet />
}
