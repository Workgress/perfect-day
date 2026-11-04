import { AuthError, getAuthRedirectPath, submitAuth, validateCredentials } from './auth'

afterEach(() => vi.unstubAllEnvs())

describe('auth boundaries', () => {
  it.each([
    'https://example.com',
    '//example.com',
    '/\\example.com',
    '/login',
    '/register?from=/today',
    undefined,
  ])('rejects unsafe or looping return path %s', (value) => {
    expect(getAuthRedirectPath(value)).toBe('/today')
  })

  it('preserves an internal return path with search and hash', () => {
    expect(getAuthRedirectPath('/calendar?date=2026-11-04#week')).toBe(
      '/calendar?date=2026-11-04#week',
    )
  })

  it('does not enforce registration password length at login', () => {
    expect(validateCredentials({ email: 'anna@example.com', password: 'x' }, 'login')).toEqual({})
    expect(
      validateCredentials({ email: 'anna@example.com', password: 'x' }, 'register').password,
    ).toBeDefined()
  })

  it('does not allow a demo session in production', async () => {
    vi.stubEnv('DEV', false)
    await expect(
      submitAuth(
        'login',
        { email: 'anna@example.com', password: 'demo-password' },
        new AbortController().signal,
      ),
    ).rejects.toBeInstanceOf(AuthError)
  })
})
