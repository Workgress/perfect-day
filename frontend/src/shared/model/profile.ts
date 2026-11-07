import type { Chronotype } from './onboarding'

export type OnboardingStep = 'birth_date' | 'chronotype' | 'first_tasks'

export type ProfileDocument = {
  local?: boolean
  id: string
  email: string
  display_name: string | null
  profile: {
    birth_date: string | null
    birth_time: string | null
    timezone: string
    chronotype: Chronotype | null
    work_start: string
    work_end: string
    sleep_time: string
  } | null
  onboarding: { completed_at: string | null; next_step: OnboardingStep | null }
}

export type ProfilePatch = Partial<NonNullable<ProfileDocument['profile']>>
