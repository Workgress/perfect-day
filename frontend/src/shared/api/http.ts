import { API_URL } from './config'

export class HttpError extends Error {
  readonly status: number
  readonly body: unknown
  readonly headers: Headers

  constructor(status: number, body: unknown, headers = new Headers()) {
    super(`HTTP ${status}`)
    this.name = 'HttpError'
    this.status = status
    this.body = body
    this.headers = headers
  }
}

type HttpConfig = {
  getAccessToken: () => string | null
  onUnauthorized: () => void
  refreshAccessToken: (() => Promise<string | null>) | null
}

const config: HttpConfig = {
  getAccessToken: () => null,
  onUnauthorized: () => {},
  refreshAccessToken: null,
}

export function configureHttp(next: Partial<HttpConfig>) {
  Object.assign(config, next)
}

type QueryValue = string | number | boolean | null | undefined

export type HttpOptions = Omit<RequestInit, 'body'> & {
  body?: unknown
  query?: Record<string, QueryValue>
  auth?: boolean
}

function buildUrl(path: string, query?: Record<string, QueryValue>) {
  const url = new URL(`${API_URL}${path}`, window.location.origin)
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== null && value !== undefined) url.searchParams.set(key, String(value))
    }
  }
  return url
}

async function readBody(response: Response): Promise<unknown> {
  if (response.status === 204) return undefined
  const contentType = response.headers.get('Content-Type') ?? ''
  return contentType.includes('application/json') ? response.json() : response.text()
}

export async function http<T>(path: string, options: HttpOptions = {}): Promise<T> {
  const { body, query, headers, auth = true, ...init } = options
  const requestHeaders = new Headers(headers)
  requestHeaders.set('Accept', 'application/json')

  const token = auth ? config.getAccessToken() : null
  const form = body instanceof URLSearchParams
  if (body !== undefined)
    requestHeaders.set(
      'Content-Type',
      form ? 'application/x-www-form-urlencoded;charset=UTF-8' : 'application/json',
    )

  const request = (accessToken: string | null) => {
    const nextHeaders = new Headers(requestHeaders)
    if (accessToken) nextHeaders.set('Authorization', `Bearer ${accessToken}`)
    return fetch(buildUrl(path, query), {
      credentials: 'include',
      ...init,
      headers: nextHeaders,
      body: body === undefined ? undefined : form ? body.toString() : JSON.stringify(body),
    })
  }
  let response = await request(token)

  if (response.status === 401 && token) {
    const currentToken = config.getAccessToken()
    const nextToken =
      currentToken !== token
        ? currentToken
        : config.refreshAccessToken
          ? await config.refreshAccessToken()
          : null
    init.signal?.throwIfAborted()
    if (nextToken) response = await request(nextToken)
    if (
      (!nextToken && config.getAccessToken() === token) ||
      (response.status === 401 && nextToken === config.getAccessToken() && nextToken !== null)
    )
      config.onUnauthorized()
  }

  const data = await readBody(response)
  if (!response.ok) throw new HttpError(response.status, data, response.headers)
  return data as T
}
