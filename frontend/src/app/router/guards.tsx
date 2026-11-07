import { Navigate, Outlet, useLocation } from 'react-router'
import { selectIsAuthenticated, selectIsOnboarded, useSessionStore } from '@/stores/session'
import { paths } from './paths'
import { onboardingPath } from './onboardingPath'

export type RedirectState = {
  from?: string
}

export function RequireAuth() {
  const location = useLocation()
  const isAuthenticated = useSessionStore(selectIsAuthenticated)

  if (!isAuthenticated) {
    const state: RedirectState = { from: location.pathname + location.search + location.hash }
    return <Navigate to={paths.login} replace state={state} />
  }
  return <Outlet />
}

export function RequireOnboarding() {
  const isOnboarded = useSessionStore(selectIsOnboarded)
  const nextStep = useSessionStore((state) => state.nextStep)
  const location = useLocation()
  return isOnboarded ? (
    <Outlet />
  ) : (
    <Navigate
      to={onboardingPath(nextStep)}
      replace
      state={{ from: location.pathname + location.search + location.hash }}
    />
  )
}

export function GuestOnly() {
  const isAuthenticated = useSessionStore(selectIsAuthenticated)
  return isAuthenticated ? <Navigate to={paths.today} replace /> : <Outlet />
}

export function OnboardingOnly() {
  const isOnboarded = useSessionStore(selectIsOnboarded)
  return isOnboarded ? <Navigate to={paths.today} replace /> : <Outlet />
}
