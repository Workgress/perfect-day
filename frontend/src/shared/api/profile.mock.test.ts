import { useSessionStore } from '@/stores/session'
import { profileFixture } from '@/test/apiServer'
import { finishOnboarding, getProfile, saveProfile } from './profile'

function signIn(id: string, email = 'anna@example.com') {
  useSessionStore
    .getState()
    .signIn({ accessToken: `header.${btoa(JSON.stringify({ sub: id }))}.signature`, email })
}

describe('local profile fallback', () => {
  beforeEach(() => {
    signIn('user-one')
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        Response.json({ error: { code: 'NOT_FOUND', message: 'Не найдено' } }, { status: 404 }),
      ),
    )
  })

  it('saves the missing profile and completes local onboarding across reloads', async () => {
    expect(await getProfile()).toMatchObject({
      id: 'user-one',
      email: 'anna@example.com',
      local: true,
      onboarding: { next_step: 'birth_date' },
    })
    expect(
      await saveProfile({ birth_date: '2003-09-20', timezone: 'Asia/Yekaterinburg' }),
    ).toMatchObject({ onboarding: { next_step: 'chronotype' } })
    expect(
      await saveProfile({ chronotype: 'owl', work_start: '12:00:00', work_end: '22:00:00' }),
    ).toMatchObject({ onboarding: { next_step: 'first_tasks' } })
    const completed = await finishOnboarding(
      {
        planned_date: '2026-11-06',
        tasks: [{ title: 'Учёба', type: 'intellectual', duration_min: 60 }],
      },
      'key-one',
    )
    expect(completed.onboarding.completed_at).toBeTruthy()
    expect(completed.onboarding.next_step).toBeNull()
    useSessionStore.getState().signOut()
    signIn('user-one')
    expect((await getProfile()).onboarding).toEqual(completed.onboarding)
    expect(localStorage.getItem('pd-local-profile:user-one')).not.toContain('signature')
  })

  it('does not mix local profiles between accounts', async () => {
    await saveProfile({ birth_date: '2003-09-20' })
    signIn('user-two', 'other@example.com')
    expect(await getProfile()).toMatchObject({
      id: 'user-two',
      email: 'other@example.com',
      profile: null,
      onboarding: { completed_at: null, next_step: 'birth_date' },
    })
    signIn('user-one')
    expect((await getProfile()).profile?.birth_date).toBe('2003-09-20')
  })

  it('prefers a real server profile as soon as the endpoint is available', async () => {
    await saveProfile({ birth_date: '2003-09-20' })
    const document = profileFixture()
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Response.json(document)),
    )
    expect(await getProfile()).toEqual(document)
    expect((await getProfile()).local).toBeUndefined()
  })

  it('does not replace server errors with local success', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => Response.json({ error: { code: 'SERVICE_UNAVAILABLE' } }, { status: 503 })),
    )
    await expect(getProfile()).rejects.toMatchObject({ status: 503 })
    await expect(saveProfile({ birth_date: '2003-09-20' })).rejects.toMatchObject({ status: 503 })
  })
})
