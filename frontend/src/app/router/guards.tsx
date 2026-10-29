import { Navigate, Outlet, useLocation } from 'react-router'
import { useSession } from '@/app/session/SessionContext'
import { paths } from './paths'

export type RedirectState = {
  from?: string
}

export function RequireAuth() {
  const location = useLocation()
  const isAuthenticated = useSession().state.isAuthenticated

  if (!isAuthenticated) {
    const state: RedirectState = { from: location.pathname + location.search }
    return <Navigate to={paths.login} replace state={state} />
  }
  return <Outlet />
}

export function RequireOnboarding() {
  const isOnboarded = useSession().state.isOnboarded
  return isOnboarded ? <Outlet /> : <Navigate to={paths.onboarding.birthDate} replace />
}

export function GuestOnly() {
  const isAuthenticated = useSession().state.isAuthenticated
  return isAuthenticated ? <Navigate to={paths.today} replace /> : <Outlet />
}

export function OnboardingOnly() {
  const isOnboarded = useSession().state.isOnboarded
  return isOnboarded ? <Navigate to={paths.today} replace /> : <Outlet />
}
