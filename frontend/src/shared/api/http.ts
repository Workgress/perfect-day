import { API_URL } from './config'

export class HttpError extends Error {
  readonly status: number
  readonly body: unknown

  constructor(status: number, body: unknown) {
    super(`HTTP ${status}`)
    this.name = 'HttpError'
    this.status = status
    this.body = body
  }
}

type HttpConfig = {
  getAccessToken: () => string | null
  onUnauthorized: () => void
}

const config: HttpConfig = {
  getAccessToken: () => null,
  onUnauthorized: () => {},
}

export function configureHttp(next: Partial<HttpConfig>) {
  Object.assign(config, next)
}

type QueryValue = string | number | boolean | null | undefined

export type HttpOptions = Omit<RequestInit, 'body'> & {
  body?: unknown
  query?: Record<string, QueryValue>
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
  const { body, query, headers, ...init } = options
  const requestHeaders = new Headers(headers)
  requestHeaders.set('Accept', 'application/json')

  const token = config.getAccessToken()
  if (token) requestHeaders.set('Authorization', `Bearer ${token}`)
  if (body !== undefined) requestHeaders.set('Content-Type', 'application/json')

  const response = await fetch(buildUrl(path, query), {
    ...init,
    headers: requestHeaders,
    body: body === undefined ? undefined : JSON.stringify(body),
  })

  if (response.status === 401 && token) config.onUnauthorized()

  const data = await readBody(response)
  if (!response.ok) throw new HttpError(response.status, data)
  return data as T
}
