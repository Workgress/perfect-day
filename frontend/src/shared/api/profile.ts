import type { ProfileDocument, ProfilePatch } from '@/shared/model/profile'
import type { OnboardingTask, OnboardingRequest } from '@/shared/model/onboarding'
import { http, HttpError } from './http'

export const PROFILE_QUERY_KEY = ['session', 'profile'] as const

export async function getProfile(signal?: AbortSignal): Promise<ProfileDocument> {
  try {
    return readProfile(await http<ProfileDocument>('/me', { signal }))
  } catch (error) {
    if (!(error instanceof HttpError) || error.status !== 404) throw error
    signal?.throwIfAborted()
    const { getLocalProfile } = await import('./profile.mock')
    return getLocalProfile()
  }
}

export async function saveProfile(patch: ProfilePatch): Promise<ProfileDocument> {
  try {
    return readProfile(await http<ProfileDocument>('/me/profile', { method: 'PATCH', body: patch }))
  } catch (error) {
    if (!(error instanceof HttpError) || error.status !== 404) throw error
    const { saveLocalProfile } = await import('./profile.mock')
    return saveLocalProfile(patch)
  }
}

export function onboardingRequest(tasks: OnboardingTask[], timezone: string): OnboardingRequest {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: timezone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date())
  const part = (type: string) => parts.find((item) => item.type === type)?.value
  return {
    planned_date: `${part('year')}-${part('month')}-${part('day')}`,
    tasks: tasks.map((task) => ({
      title: task.title.trim(),
      type: task.type,
      duration_min: task.durationMin,
    })),
  }
}

export async function finishOnboarding(
  body: OnboardingRequest,
  key: string,
): Promise<ProfileDocument> {
  let document: ProfileDocument
  try {
    document = readProfile(
      await http<ProfileDocument>('/onboarding/complete', {
        method: 'POST',
        headers: { 'Idempotency-Key': key },
        body,
      }),
    )
  } catch (error) {
    if (!(error instanceof HttpError) || error.status !== 404) throw error
    const { finishLocalOnboarding } = await import('./profile.mock')
    return finishLocalOnboarding(body)
  }
  if (!document.onboarding.completed_at || document.onboarding.next_step !== null)
    throw new Error('Сервер не подтвердил завершение настройки.')
  return document
}

function readProfile(value: ProfileDocument): ProfileDocument {
  if (
    !value ||
    typeof value.id !== 'string' ||
    typeof value.email !== 'string' ||
    !value.onboarding ||
    !['birth_date', 'chronotype', 'first_tasks', null].includes(value.onboarding.next_step)
  ) {
    throw new Error('Не удалось прочитать ответ профиля. Попробуйте позже.')
  }
  if ((value.onboarding.next_step === null) !== Boolean(value.onboarding.completed_at))
    throw new Error('Сервер вернул некорректный статус настройки.')
  const profile = value.profile
  if (
    profile !== null &&
    (!profile ||
      typeof profile.timezone !== 'string' ||
      typeof profile.work_start !== 'string' ||
      typeof profile.work_end !== 'string' ||
      typeof profile.sleep_time !== 'string' ||
      !['lark', 'dove', 'owl', null].includes(profile.chronotype))
  )
    throw new Error('Сервер вернул некорректный профиль.')
  if (value.onboarding.completed_at && (!profile?.birth_date || !profile.chronotype))
    throw new Error('Сервер не подтвердил заполнение профиля.')
  return value
}
