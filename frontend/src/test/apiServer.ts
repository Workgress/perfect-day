import type { ProfileDocument } from '@/shared/model/profile'
import type { SessionUser } from '@/stores/session'

export function profileFixture(
  user: Partial<SessionUser> = {},
  completed = false,
): ProfileDocument {
  const birthDate = user.birthDate ?? (completed ? '2003-09-20' : null)
  const chronotype = user.chronotype ?? (completed ? 'lark' : null)
  return {
    id: user.id ?? 'user-one',
    email: user.email ?? 'anna@example.com',
    display_name: user.name ?? 'Анна',
    profile: birthDate
      ? {
          birth_date: birthDate,
          birth_time: user.birthTime ?? null,
          timezone: 'Asia/Yekaterinburg',
          chronotype,
          work_start: '08:00:00',
          work_end: '18:00:00',
          sleep_time: '23:00:00',
        }
      : null,
    onboarding: {
      completed_at: completed ? '2026-11-06T08:00:00Z' : null,
      next_step: completed
        ? null
        : !birthDate
          ? 'birth_date'
          : !chronotype
            ? 'chronotype'
            : 'first_tasks',
    },
  }
}

export function installApiServer(initial = profileFixture(), authenticated = false) {
  let document = structuredClone(initial)
  let active = authenticated
  const fetchMock = vi.fn(async (input: URL | string, init?: RequestInit) => {
    const path = new URL(String(input)).pathname
    if (path.endsWith('/auth/refresh'))
      return active
        ? Response.json({ access_token: 'refreshed-token', token_type: 'bearer', expires_in: 900 })
        : Response.json(
            { error: { code: 'INVALID_REFRESH_TOKEN', message: 'Сессия истекла' } },
            { status: 401 },
          )
    if (path.endsWith('/auth/login') || path.endsWith('/auth/verify-email')) {
      active = true
      return Response.json({
        access_token: 'real-test-token',
        token_type: 'bearer',
        expires_in: 900,
      })
    }
    if (path.endsWith('/auth/logout')) {
      active = false
      return new Response(null, { status: 204 })
    }
    if (path.endsWith('/me')) return Response.json(document)
    if (path.endsWith('/me/profile')) {
      const patch = JSON.parse(String(init?.body)) as Record<string, unknown>
      document.profile = {
        birth_date: null,
        birth_time: null,
        timezone: 'UTC',
        chronotype: null,
        work_start: '08:00:00',
        work_end: '18:00:00',
        sleep_time: '23:00:00',
        ...document.profile,
        ...patch,
      }
      document.onboarding.next_step = document.profile.chronotype ? 'first_tasks' : 'chronotype'
      return Response.json(document)
    }
    if (path.endsWith('/onboarding/complete')) {
      document.onboarding = { completed_at: '2026-11-06T08:00:00Z', next_step: null }
      return Response.json(document)
    }
    if (path.endsWith('/health')) return Response.json({ status: 'ok' })
    if (path.endsWith('/auth/register') || path.endsWith('/auth/resend-verification'))
      return Response.json(
        { message: 'Если действие доступно для указанного адреса, письмо будет отправлено' },
        { status: 202 },
      )
    return Response.json({ error: { code: 'NOT_FOUND', message: 'Не найдено' } }, { status: 404 })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}
