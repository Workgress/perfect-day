import { http } from './http'

export type TokenResponse = { access_token: string; token_type: 'bearer'; expires_in: number }

let queue: Promise<unknown> = Promise.resolve()

export function withSessionLock<T>(operation: () => Promise<T>): Promise<T> {
  const run = () =>
    navigator.locks ? navigator.locks.request('pd-auth-session', operation) : operation()
  const next = queue.then(run, run)
  queue = next.catch(() => {})
  return next
}

export function requestTokens(
  path: '/auth/login' | '/auth/verify-email' | '/auth/refresh',
  body?: unknown,
  signal?: AbortSignal,
): Promise<TokenResponse> {
  return withSessionLock(async () => {
    signal?.throwIfAborted()
    const token = await http<TokenResponse>(path, { method: 'POST', body, signal, auth: false })
    if (
      !token.access_token ||
      token.token_type !== 'bearer' ||
      !Number.isFinite(token.expires_in) ||
      token.expires_in <= 0
    )
      throw new Error('Некорректный ответ авторизации.')
    return token
  })
}

export function requestLogout(): Promise<void> {
  return withSessionLock(() => http<void>('/auth/logout', { method: 'POST', auth: false }))
}
