import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import { EMPTY_ONBOARDING, type Chronotype, type OnboardingDraft } from '@/shared/model/onboarding'
import type { OnboardingStep, ProfileDocument } from '@/shared/model/profile'

export type { Chronotype } from '@/shared/model/onboarding'

export type SessionUser = {
  id?: string
  email?: string
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
  expiresAt: number | null
  status: 'restoring' | 'guest' | 'authenticated'
  generation: number
  user: SessionUser | null
  isOnboarded: boolean
  nextStep: OnboardingStep
  timezone: string
  ownerId: string | null
  emailHint: string | null
  isLocalProfile: boolean
  onboarding: OnboardingDraft
}

type SessionActions = {
  signIn: (session: {
    accessToken: string
    expiresIn?: number
    user?: SessionUser
    email?: string
  }) => void
  setAccessToken: (token: string, expiresIn: number) => void
  applyProfile: (document: ProfileDocument) => void
  updateOnboarding: (patch: Partial<OnboardingDraft>) => void
  signOut: () => void
}

export type SessionStore = SessionState & SessionActions

const GUEST: SessionState = {
  accessToken: null,
  expiresAt: null,
  status: 'restoring',
  generation: 0,
  user: null,
  isOnboarded: false,
  nextStep: 'birth_date',
  timezone: 'UTC',
  ownerId: null,
  emailHint: null,
  isLocalProfile: false,
  onboarding: EMPTY_ONBOARDING,
}

export const useSessionStore = create<SessionStore>()(
  persist(
    (set) => ({
      ...GUEST,
      signIn: ({ accessToken, expiresIn = 900, user, email }) =>
        set((state) => ({
          accessToken,
          expiresAt: Date.now() + expiresIn * 1000,
          status: 'authenticated',
          generation: state.generation + 1,
          user: user ?? null,
          emailHint: email ?? user?.email ?? null,
          isLocalProfile: false,
          isOnboarded: false,
          nextStep: 'birth_date',
        })),
      setAccessToken: (accessToken, expiresIn) =>
        set({ accessToken, expiresAt: Date.now() + expiresIn * 1000, status: 'authenticated' }),
      applyProfile: (document) =>
        set((state) => {
          const profile = document.profile
          const user: SessionUser = {
            id: document.id,
            email: document.email,
            name: document.display_name ?? document.email,
            birthDate: profile?.birth_date ?? null,
            birthTime: profile?.birth_time?.slice(0, 5) ?? null,
            chronotype: profile?.chronotype ?? null,
            workStart: profile?.work_start.slice(0, 5) ?? '08:00',
            workEnd: profile?.work_end.slice(0, 5) ?? '18:00',
            sleepTime: profile?.sleep_time.slice(0, 5) ?? '23:00',
          }
          const draft =
            state.ownerId === document.id
              ? state.onboarding
              : {
                  ...EMPTY_ONBOARDING,
                  birthDate: user.birthDate?.split('-').reverse().join('.') ?? '',
                  birthTime: user.birthTime ?? '',
                  chronotype: user.chronotype ?? 'lark',
                  workStart: user.workStart!,
                  workEnd: user.workEnd!,
                  sleepTime: user.sleepTime!,
                }
          return {
            user,
            isLocalProfile: document.local === true,
            ownerId: document.id,
            isOnboarded: Boolean(document.onboarding.completed_at),
            nextStep: document.onboarding.next_step ?? 'first_tasks',
            timezone: profile?.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone,
            onboarding: draft,
          }
        }),
      updateOnboarding: (patch) =>
        set((state) =>
          state.accessToken
            ? {
                onboarding: {
                  ...state.onboarding,
                  completion: undefined,
                  ...patch,
                },
              }
            : state,
        ),
      signOut: () =>
        set((state) => ({ ...GUEST, status: 'guest', generation: state.generation + 1 })),
    }),
    {
      name: 'pd-session',
      version: 2,
      storage: createJSONStorage(() => localStorage),
      partialize: ({ ownerId, onboarding }) => ({ ownerId, onboarding }),
      migrate: () => ({ ownerId: null, onboarding: EMPTY_ONBOARDING }),
      merge: (persisted, current) => {
        const data = persisted as { ownerId?: string; onboarding?: OnboardingDraft } | null
        return {
          ...current,
          ownerId: typeof data?.ownerId === 'string' ? data.ownerId : null,
          onboarding: data?.onboarding
            ? { ...EMPTY_ONBOARDING, ...data.onboarding }
            : EMPTY_ONBOARDING,
        }
      },
    },
  ),
)

export const selectIsAuthenticated = (state: SessionStore) => state.accessToken !== null
export const selectIsOnboarded = (state: SessionStore) => state.isOnboarded
export const selectUserName = (state: SessionStore) => state.user?.name ?? null
