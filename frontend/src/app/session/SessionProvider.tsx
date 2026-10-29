import { useMemo, useState, type ReactNode } from 'react'
import { SessionContext, type SessionState } from './SessionContext'

const GUEST: SessionState = {
  isAuthenticated: false,
  isOnboarded: false,
  userName: null,
}

type SessionProviderProps = {
  initialState?: SessionState
  children: ReactNode
}

export function SessionProvider({ initialState = GUEST, children }: SessionProviderProps) {
  const [state, setState] = useState(initialState)

  const actions = useMemo(
    () => ({
      signIn: (userName: string) =>
        setState((current) => ({ ...current, isAuthenticated: true, userName })),
      completeOnboarding: () => setState((current) => ({ ...current, isOnboarded: true })),
      signOut: () => setState(GUEST),
    }),
    [],
  )

  const value = useMemo(() => ({ state, actions }), [state, actions])

  return <SessionContext value={value}>{children}</SessionContext>
}
