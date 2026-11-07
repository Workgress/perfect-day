import { selectIsAuthenticated, selectUserName, useSessionStore } from './session'
import { EMPTY_ONBOARDING } from '@/shared/model/onboarding'
import type { ProfileDocument } from '@/shared/model/profile'

const SESSION = { accessToken: 'secret-token', expiresIn: 900 }
const PROFILE: ProfileDocument = {
  id: 'user-one',
  email: 'anna@example.com',
  display_name: 'Анна',
  profile: null,
  onboarding: { completed_at: null, next_step: 'birth_date' },
}

function readPersisted() {
  return JSON.parse(localStorage.getItem('pd-session') ?? 'null')
}

describe('session store', () => {
  it('starts without authorization and waits for server restoration', () => {
    expect(selectIsAuthenticated(useSessionStore.getState())).toBe(false)
    expect(useSessionStore.getState().status).toBe('restoring')
  })

  it('keeps access and user state out of persistent storage', () => {
    useSessionStore.getState().signIn(SESSION)
    useSessionStore.getState().applyProfile(PROFILE)
    expect(selectUserName(useSessionStore.getState())).toBe('Анна')
    expect(readPersisted()).toEqual({
      state: { ownerId: 'user-one', onboarding: EMPTY_ONBOARDING },
      version: 2,
    })
    expect(JSON.stringify(readPersisted())).not.toContain('secret-token')
    expect(JSON.stringify(readPersisted())).not.toContain('anna@example.com')
  })

  it('trusts only the server onboarding status', () => {
    useSessionStore.getState().signIn(SESSION)
    useSessionStore.getState().updateOnboarding({ birthDate: '20.09.2003', chronotype: 'owl' })
    expect(useSessionStore.getState().isOnboarded).toBe(false)
    useSessionStore.getState().applyProfile({
      ...PROFILE,
      onboarding: { completed_at: '2026-11-06T08:00:00Z', next_step: null },
    })
    expect(useSessionStore.getState().isOnboarded).toBe(true)
  })

  it('restores a draft only for its owner without restoring authorization', async () => {
    useSessionStore.getState().signIn(SESSION)
    useSessionStore.getState().applyProfile(PROFILE)
    useSessionStore.getState().updateOnboarding({ birthDate: '20.09.2003', birthTime: '14:15' })
    const saved = localStorage.getItem('pd-session')!
    useSessionStore.setState(useSessionStore.getInitialState(), true)
    localStorage.setItem('pd-session', saved)
    await useSessionStore.persist.rehydrate()
    expect(useSessionStore.getState().accessToken).toBeNull()
    useSessionStore.getState().signIn(SESSION)
    useSessionStore.getState().applyProfile(PROFILE)
    expect(useSessionStore.getState().onboarding.birthTime).toBe('14:15')
    useSessionStore.getState().applyProfile({ ...PROFILE, id: 'other-user' })
    expect(useSessionStore.getState().onboarding.birthTime).toBe('')
  })

  it('discards legacy persisted demo authorization', async () => {
    localStorage.setItem(
      'pd-session',
      JSON.stringify({
        version: 1,
        state: { accessToken: 'demo-token', isOnboarded: true, user: { name: 'Анна' } },
      }),
    )
    await useSessionStore.persist.rehydrate()
    expect(useSessionStore.getState().accessToken).toBeNull()
    expect(useSessionStore.getState().isOnboarded).toBe(false)
    expect(localStorage.getItem('pd-session')).not.toContain('demo-token')
  })

  it('clears owner draft and authorization on logout', () => {
    useSessionStore.getState().signIn(SESSION)
    useSessionStore.getState().applyProfile(PROFILE)
    useSessionStore.getState().signOut()
    expect(useSessionStore.getState()).toMatchObject({
      accessToken: null,
      user: null,
      status: 'guest',
      ownerId: null,
      isOnboarded: false,
    })
    expect(readPersisted().state).toEqual({ ownerId: null, onboarding: EMPTY_ONBOARDING })
  })
})
