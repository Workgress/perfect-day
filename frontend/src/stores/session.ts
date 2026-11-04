import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import { EMPTY_ONBOARDING, type Chronotype, type OnboardingDraft } from '@/shared/model/onboarding'

export type { Chronotype } from '@/shared/model/onboarding'

export type SessionUser = {
  name: string
  birthDate: string | null
  chronotype: Chronotype | null
  birthTime?: string | null
  workStart?: string
  workEnd?: string
  sleepTime?: string
}

type SessionState = {
  accessToken: string | null
  user: SessionUser | null
  isOnboarded: boolean
  onboarding: OnboardingDraft
}

type SessionActions = {
  signIn: (session: { accessToken: string; user: SessionUser }) => void
  updateUser: (patch: Partial<SessionUser>) => void
  updateOnboarding: (patch: Partial<OnboardingDraft>) => void
  completeOnboarding: () => void
  signOut: () => void
}

export type SessionStore = SessionState & SessionActions

const GUEST: SessionState = {
  accessToken: null,
  user: null,
  isOnboarded: false,
  onboarding: EMPTY_ONBOARDING,
}

export const useSessionStore = create<SessionStore>()(
  persist(
    (set) => ({
      ...GUEST,
      signIn: ({ accessToken, user }) =>
        set({
          ...GUEST,
          accessToken,
          user,
          onboarding: {
            ...EMPTY_ONBOARDING,
            birthDate: user.birthDate ? user.birthDate.split('-').reverse().join('.') : '',
            birthTime: user.birthTime ?? '',
            chronotype: user.chronotype ?? 'lark',
            workStart: user.workStart ?? '08:00',
            workEnd: user.workEnd ?? '18:00',
            sleepTime: user.sleepTime ?? '23:00',
          },
        }),
      updateUser: (patch) =>
        set((state) => (state.user ? { user: { ...state.user, ...patch } } : state)),
      updateOnboarding: (patch) =>
        set((state) =>
          state.user ? { onboarding: { ...state.onboarding, planReady: false, ...patch } } : state,
        ),
      completeOnboarding: () => set({ isOnboarded: true }),
      signOut: () => set(GUEST),
    }),
    {
      name: 'pd-session',
      version: 1,
      storage: createJSONStorage(() => localStorage),
      partialize: ({ accessToken, user, isOnboarded, onboarding }): SessionState => ({
        accessToken,
        user,
        isOnboarded,
        onboarding,
      }),
    },
  ),
)

export const selectIsAuthenticated = (state: SessionStore) => state.accessToken !== null
export const selectIsOnboarded = (state: SessionStore) => state.isOnboarded
export const selectUserName = (state: SessionStore) => state.user?.name ?? null
