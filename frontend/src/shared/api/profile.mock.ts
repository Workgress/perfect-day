import type { ProfileDocument, ProfilePatch } from '@/shared/model/profile'
import type { OnboardingRequest } from '@/shared/model/onboarding'
import { useSessionStore } from '@/stores/session'

type LocalProfile = { document: ProfileDocument; tasks: OnboardingRequest['tasks'] }

function identity() {
  const session = useSessionStore.getState()
  if (!session.accessToken) throw new Error('Сначала войдите в аккаунт.')
  let id = session.user?.id
  try {
    const payload = session.accessToken.split('.')[1]
    const claims = JSON.parse(atob(payload.replace(/-/g, '+').replace(/_/g, '/'))) as {
      sub?: unknown
    }
    if (typeof claims.sub === 'string' && claims.sub) id = claims.sub
  } catch {}
  if (!id)
    throw new Error('Не удалось определить аккаунт для локального профиля. Войдите повторно.')
  return {
    id,
    email: session.emailHint ?? session.user?.email ?? '',
    key: `pd-local-profile:${id}`,
  }
}

function load(): LocalProfile {
  const account = identity()
  const saved = localStorage.getItem(account.key)
  if (saved) {
    try {
      const profile = JSON.parse(saved) as LocalProfile
      if (
        profile.document.id === account.id &&
        profile.document.onboarding &&
        Array.isArray(profile.tasks)
      ) {
        profile.document.local = true
        if (account.email) {
          profile.document.email = account.email
          profile.document.display_name = null
        }
        return profile
      }
    } catch {}
  }
  return {
    document: {
      id: account.id,
      email: account.email,
      display_name: account.email ? null : 'Пользователь',
      profile: null,
      onboarding: { completed_at: null, next_step: 'birth_date' },
      local: true,
    },
    tasks: [],
  }
}

function persist(value: LocalProfile): ProfileDocument {
  localStorage.setItem(identity().key, JSON.stringify(value))
  return value.document
}

export function getLocalProfile(): ProfileDocument {
  return persist(load())
}

export function saveLocalProfile(patch: ProfilePatch): ProfileDocument {
  const value = load()
  value.document.profile = {
    birth_date: null,
    birth_time: null,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    chronotype: null,
    work_start: '08:00:00',
    work_end: '18:00:00',
    sleep_time: '23:00:00',
    ...value.document.profile,
    ...patch,
  }
  const profile = value.document.profile
  if (!value.document.onboarding.completed_at)
    value.document.onboarding.next_step = !profile.birth_date
      ? 'birth_date'
      : !profile.chronotype
        ? 'chronotype'
        : 'first_tasks'
  return persist(value)
}

export function finishLocalOnboarding(body: OnboardingRequest): ProfileDocument {
  const value = load()
  if (!value.document.profile?.birth_date || !value.document.profile.chronotype)
    throw new Error('Сначала заполните дату рождения и хронотип.')
  value.tasks = body.tasks
  value.document.onboarding = {
    completed_at: value.document.onboarding.completed_at ?? new Date().toISOString(),
    next_step: null,
  }
  return persist(value)
}
