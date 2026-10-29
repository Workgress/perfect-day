import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

export type Chronotype = 'lark' | 'owl' | 'dove'

export type SessionUser = {
  name: string
  birthDate: string | null
  chronotype: Chronotype | null
}

type SessionState = {
  accessToken: string | null
  user: SessionUser | null
  isOnboarded: boolean
}

type SessionActions = {
  signIn: (session: { accessToken: string; user: SessionUser }) => void
  updateUser: (patch: Partial<SessionUser>) => void
  completeOnboarding: () => void
  signOut: () => void
}

export type SessionStore = SessionState & SessionActions

const GUEST: SessionState = {
  accessToken: null,
  user: null,
  isOnboarded: false,
}

export const useSessionStore = create<SessionStore>()(
  persist(
    (set) => ({
      ...GUEST,
      signIn: ({ accessToken, user }) => set({ accessToken, user }),
      updateUser: (patch) =>
        set((state) => (state.user ? { user: { ...state.user, ...patch } } : state)),
      completeOnboarding: () => set({ isOnboarded: true }),
      signOut: () => set(GUEST),
    }),
    {
      name: 'pd-session',
      version: 1,
      storage: createJSONStorage(() => localStorage),
      partialize: ({ accessToken, user, isOnboarded }): SessionState => ({
        accessToken,
        user,
        isOnboarded,
      }),
    },
  ),
)

export const selectIsAuthenticated = (state: SessionStore) => state.accessToken !== null
export const selectIsOnboarded = (state: SessionStore) => state.isOnboarded
export const selectUserName = (state: SessionStore) => state.user?.name ?? null
