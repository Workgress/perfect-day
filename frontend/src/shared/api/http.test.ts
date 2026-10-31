import { configureHttp, http, HttpError } from './http'

function mockFetch(response: Response) {
  const fetchMock = vi.fn(async (_input: URL, _init?: RequestInit) => response)
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function lastRequest(fetchMock: ReturnType<typeof mockFetch>) {
  const [url, init] = fetchMock.mock.calls[0]
  return { url: url.toString(), init: init ?? {}, headers: new Headers(init?.headers) }
}

describe('http', () => {
  const onUnauthorized = vi.fn()

  beforeEach(() => {
    onUnauthorized.mockReset()
    configureHttp({ getAccessToken: () => null, onUnauthorized })
  })

  it('requests JSON from the API prefix with query params', async () => {
    const fetchMock = mockFetch(Response.json({ status: 'ok' }))

    const data = await http<{ status: string }>('/tasks', {
      query: { date: '2026-10-14', page: 2, skipped: undefined },
    })

    const { url, headers } = lastRequest(fetchMock)
    expect(data).toEqual({ status: 'ok' })
    expect(url).toBe(`${window.location.origin}/api/v1/tasks?date=2026-10-14&page=2`)
    expect(headers.get('Accept')).toBe('application/json')
    expect(headers.has('Authorization')).toBe(false)
  })

  it('sends bearer token and JSON body', async () => {
    configureHttp({ getAccessToken: () => 'token' })
    const fetchMock = mockFetch(new Response(null, { status: 204 }))

    const data = await http('/tasks', { method: 'POST', body: { title: 'Курсовая' } })

    const { init, headers } = lastRequest(fetchMock)
    expect(data).toBeUndefined()
    expect(init.method).toBe('POST')
    expect(init.body).toBe(JSON.stringify({ title: 'Курсовая' }))
    expect(headers.get('Authorization')).toBe('Bearer token')
    expect(headers.get('Content-Type')).toBe('application/json')
  })

  it('throws HttpError with status and body', async () => {
    mockFetch(Response.json({ detail: 'Not found' }, { status: 404 }))

    const error = await http('/tasks/1').catch((reason: unknown) => reason)

    expect(error).toBeInstanceOf(HttpError)
    expect(error).toMatchObject({ status: 404, body: { detail: 'Not found' } })
  })

  it('reports 401 for an authorized request', async () => {
    configureHttp({ getAccessToken: () => 'expired' })
    mockFetch(Response.json({ detail: 'Unauthorized' }, { status: 401 }))

    await expect(http('/me')).rejects.toBeInstanceOf(HttpError)
    expect(onUnauthorized).toHaveBeenCalledOnce()
  })

  it('does not report 401 without a token', async () => {
    mockFetch(Response.json({ detail: 'Unauthorized' }, { status: 401 }))

    await expect(http('/login')).rejects.toBeInstanceOf(HttpError)
    expect(onUnauthorized).not.toHaveBeenCalled()
  })
})
