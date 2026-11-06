import { AuthError, getAuthRedirectPath, submitAuth, validateCredentials } from './auth'
import { installApiServer } from '@/test/apiServer'

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

  it('uses the actual form contract in production', async () => {
    vi.stubEnv('DEV', false)
    const fetchMock = installApiServer()
    const result = await submitAuth(
      'login',
      { email: 'anna@example.com', password: 'Testpass123' },
      new AbortController().signal,
    )
    expect(result).toMatchObject({
      status: 'authenticated',
      session: { accessToken: 'real-test-token', expiresIn: 900 },
    })
    const init = fetchMock.mock.calls[0][1]!
    expect(new URLSearchParams(String(init.body)).get('username')).toBe('anna@example.com')
    expect(new Headers(init.headers).get('Content-Type')).toContain(
      'application/x-www-form-urlencoded',
    )
    expect(init.credentials).toBe('include')
  })

  it('normalizes server field errors and respects Retry-After', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        Response.json(
          {
            error: {
              code: 'VALIDATION_ERROR',
              message: 'Проверьте поля',
              details: { fields: [{ field: 'body.password', message: 'Добавьте цифру' }] },
            },
          },
          { status: 422, headers: { 'Retry-After': '15' } },
        ),
      ),
    )
    const error = await submitAuth(
      'register',
      { email: 'anna@example.com', password: 'password' },
      new AbortController().signal,
    ).catch((reason: unknown) => reason)
    expect(error).toBeInstanceOf(AuthError)
    expect(error).toMatchObject({
      fields: { password: 'Добавьте цифру' },
      code: 'VALIDATION_ERROR',
      retryAfter: 15,
    })
  })

  it('requires a letter and digit at registration', () => {
    expect(
      validateCredentials({ email: 'anna@example.com', password: 'abcdefgh' }, 'register').password,
    ).toContain('букву и одну цифру')
    expect(
      validateCredentials({ email: 'anna@example.com', password: '12345678' }, 'register').password,
    ).toContain('букву и одну цифру')
  })
})
