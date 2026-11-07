import { waitFor } from '@testing-library/react'
import { http, HttpError } from '@/shared/api/http'
import { useSessionStore } from '@/stores/session'
import { refreshAccessToken, restoreSession, logoutSession } from './session'

const tokenResponse = () =>
  Response.json({ access_token: 'new-token', token_type: 'bearer', expires_in: 900 })
const unauthorized = () =>
  Response.json(
    { error: { code: 'INVALID_REFRESH_TOKEN', message: 'Сессия истекла' } },
    { status: 401 },
  )

describe('session lifecycle', () => {
  it('restores through a cookie request without persisting access', async () => {
    const fetchMock = vi.fn(async () => tokenResponse())
    vi.stubGlobal('fetch', fetchMock)
    await restoreSession()
    expect(useSessionStore.getState().accessToken).toBe('new-token')
    expect(localStorage.getItem('pd-session')).not.toContain('new-token')
    expect(fetchMock.mock.calls.length).toBe(1)
  })

  it('shares one refresh between concurrent unauthorized requests and retries each once', async () => {
    useSessionStore.getState().signIn({ accessToken: 'expired' })
    let resolveRefresh!: (response: Response) => void
    const refresh = new Promise<Response>((resolve) => {
      resolveRefresh = resolve
    })
    const fetchMock = vi.fn(async (input: URL, init?: RequestInit) => {
      if (String(input).endsWith('/auth/refresh')) return refresh
      return new Headers(init?.headers).get('Authorization') === 'Bearer new-token'
        ? Response.json({ ok: true })
        : unauthorized()
    })
    vi.stubGlobal('fetch', fetchMock)
    const requests = [http('/one'), http('/two')]
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.filter(([input]) => String(input).endsWith('/auth/refresh')),
      ).toHaveLength(1),
    )
    resolveRefresh(tokenResponse())
    await expect(Promise.all(requests)).resolves.toEqual([{ ok: true }, { ok: true }])
    expect(fetchMock).toHaveBeenCalledTimes(5)
  })

  it('expires authorization when refresh is rejected', async () => {
    useSessionStore.getState().signIn({ accessToken: 'expired' })
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => unauthorized()),
    )
    await expect(http('/protected')).rejects.toBeInstanceOf(HttpError)
    expect(useSessionStore.getState().status).toBe('guest')
    expect(useSessionStore.getState().accessToken).toBeNull()
  })

  it('preserves authorization and draft on a temporary refresh failure', async () => {
    useSessionStore.getState().signIn({ accessToken: 'expired' })
    useSessionStore.getState().updateOnboarding({ birthDate: '20.09.2003' })
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: URL) =>
        String(input).endsWith('/auth/refresh')
          ? Response.json({ error: { code: 'SERVICE_UNAVAILABLE' } }, { status: 503 })
          : unauthorized(),
      ),
    )
    await expect(http('/protected')).rejects.toMatchObject({ status: 503 })
    expect(useSessionStore.getState().accessToken).toBe('expired')
    expect(useSessionStore.getState().onboarding.birthDate).toBe('20.09.2003')
  })

  it('does not restore a session from a late refresh after logout', async () => {
    useSessionStore.getState().signIn({ accessToken: 'expired' })
    let resolve!: (response: Response) => void
    vi.stubGlobal(
      'fetch',
      vi.fn(
        () =>
          new Promise<Response>((done) => {
            resolve = done
          }),
      ),
    )
    const request = refreshAccessToken()
    await waitFor(() => expect(resolve).toBeDefined())
    useSessionStore.getState().signOut()
    resolve(tokenResponse())
    await expect(request).resolves.toBeNull()
    expect(useSessionStore.getState().accessToken).toBeNull()
  })

  it('does not retry a repeatedly unauthorized protected request', async () => {
    useSessionStore.getState().signIn({ accessToken: 'expired' })
    const fetchMock = vi.fn(async (input: URL) =>
      String(input).endsWith('/auth/refresh') ? tokenResponse() : unauthorized(),
    )
    vi.stubGlobal('fetch', fetchMock)
    await expect(http('/protected')).rejects.toMatchObject({ status: 401 })
    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(useSessionStore.getState().accessToken).toBeNull()
  })

  it('logs out on the server before clearing local authorization', async () => {
    useSessionStore.getState().signIn({ accessToken: 'current' })
    const fetchMock = vi.fn(async (_input: URL, init?: RequestInit) => {
      expect(useSessionStore.getState().accessToken).toBe('current')
      expect(init?.credentials).toBe('include')
      expect(new Headers(init?.headers).has('Authorization')).toBe(false)
      return new Response(null, { status: 204 })
    })
    vi.stubGlobal('fetch', fetchMock)
    await logoutSession()
    expect(useSessionStore.getState().status).toBe('guest')
  })
})
