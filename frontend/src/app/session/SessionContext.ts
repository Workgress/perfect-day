import { createContext, use } from 'react'

export type SessionState = {
  isAuthenticated: boolean
  isOnboarded: boolean
  userName: string | null
}

export type SessionActions = {
  signIn: (userName: string) => void
  completeOnboarding: () => void
  signOut: () => void
}

export type SessionContextValue = {
  state: SessionState
  actions: SessionActions
}

export const SessionContext = createContext<SessionContextValue | null>(null)

export function useSession() {
  const context = use(SessionContext)
  if (!context) {
    throw new Error('useSession must be used inside SessionProvider')
  }
  return context
}
