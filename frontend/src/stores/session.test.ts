import { selectIsAuthenticated, selectUserName, useSessionStore } from './session'

const SESSION = {
  accessToken: 'token',
  user: { name: 'Анна', birthDate: null, chronotype: null },
}

function readPersisted() {
  return JSON.parse(localStorage.getItem('pd-session') ?? 'null')
}

describe('session store', () => {
  it('starts as a guest', () => {
    const state = useSessionStore.getState()
    expect(selectIsAuthenticated(state)).toBe(false)
    expect(selectUserName(state)).toBeNull()
    expect(state.isOnboarded).toBe(false)
  })

  it('signs in and persists only session data', () => {
    useSessionStore.getState().signIn(SESSION)

    const state = useSessionStore.getState()
    expect(selectIsAuthenticated(state)).toBe(true)
    expect(selectUserName(state)).toBe('Анна')
    expect(readPersisted()).toEqual({
      state: { accessToken: 'token', user: SESSION.user, isOnboarded: false },
      version: 1,
    })
  })

  it('updates user fields', () => {
    useSessionStore.getState().signIn(SESSION)
    useSessionStore.getState().updateUser({ chronotype: 'owl', birthDate: '2003-09-20' })
    expect(useSessionStore.getState().user).toEqual({
      name: 'Анна',
      chronotype: 'owl',
      birthDate: '2003-09-20',
    })
  })

  it('ignores user updates for a guest', () => {
    useSessionStore.getState().updateUser({ name: 'Борис' })
    expect(useSessionStore.getState().user).toBeNull()
  })

  it('completes onboarding', () => {
    useSessionStore.getState().signIn(SESSION)
    useSessionStore.getState().completeOnboarding()
    expect(useSessionStore.getState().isOnboarded).toBe(true)
    expect(readPersisted().state.isOnboarded).toBe(true)
  })

  it('signs out and clears everything', () => {
    useSessionStore.getState().signIn(SESSION)
    useSessionStore.getState().completeOnboarding()
    useSessionStore.getState().signOut()

    const state = useSessionStore.getState()
    expect(selectIsAuthenticated(state)).toBe(false)
    expect(state.isOnboarded).toBe(false)
    expect(readPersisted().state).toEqual({ accessToken: null, user: null, isOnboarded: false })
  })
})
