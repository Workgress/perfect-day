import { paths } from '@/app/router/paths'
import type { SessionUser } from '@/stores/session'
import { requestTokens } from '@/shared/api/auth'
import { http, HttpError } from '@/shared/api/http'
import { apiError } from '@/shared/api/errors'

export type AuthMode = 'login' | 'register'
export type AuthCredentials = { email: string; password: string }
export type AuthFieldErrors = Partial<Record<keyof AuthCredentials, string>>
export type AuthResult =
  | {
      status: 'authenticated'
      session: { accessToken: string; expiresIn?: number; user?: SessionUser }
    }
  | { status: 'verification_required'; resendAfterSeconds: number }

export class AuthError extends Error {
  readonly fields: AuthFieldErrors
  readonly code: string | undefined
  readonly retryAfter: number

  constructor(message: string, fields: AuthFieldErrors = {}, code?: string, retryAfter = 0) {
    super(message)
    this.name = 'AuthError'
    this.fields = fields
    this.code = code
    this.retryAfter = retryAfter
  }
}

export function validateCredentials(credentials: AuthCredentials, mode: AuthMode): AuthFieldErrors {
  const errors: AuthFieldErrors = {}
  const email = credentials.email.trim()

  if (!email) errors.email = 'Укажите email'
  else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/u.test(email)) errors.email = 'Проверьте адрес почты'

  if (!credentials.password) errors.password = 'Введите пароль'
  else if (mode === 'register') {
    const length = Array.from(credentials.password).length
    if (length < 8) errors.password = 'Используйте не менее 8 символов'
    else if (length > 128) errors.password = 'Используйте не более 128 символов'
    else if (!/\p{L}/u.test(credentials.password) || !/\p{N}/u.test(credentials.password))
      errors.password = 'Добавьте хотя бы одну букву и одну цифру'
  }

  return errors
}

export function getAuthRedirectPath(from: unknown): string {
  if (
    typeof from !== 'string' ||
    !from.startsWith('/') ||
    from.startsWith('//') ||
    from.includes('\\')
  ) {
    return paths.today
  }
  const pathname = from.split(/[?#]/u)[0]
  return pathname === paths.login || pathname === paths.register ? paths.today : from
}

export async function submitAuth(
  mode: AuthMode,
  credentials: AuthCredentials,
  signal: AbortSignal,
): Promise<AuthResult> {
  try {
    if (mode === 'register') {
      await http('/auth/register', {
        method: 'POST',
        body: { email: credentials.email.trim(), password: credentials.password },
        signal,
        auth: false,
      })
      return { status: 'verification_required', resendAfterSeconds: 60 }
    }
    const form = new URLSearchParams({
      username: credentials.email.trim(),
      password: credentials.password,
      grant_type: 'password',
    })
    const token = await requestTokens('/auth/login', form, signal)
    return {
      status: 'authenticated',
      session: { accessToken: token.access_token, expiresIn: token.expires_in },
    }
  } catch (error) {
    throw normalizeAuthError(error)
  }
}

export async function resendConfirmation(email: string, signal: AbortSignal): Promise<number> {
  try {
    await http('/auth/resend-verification', {
      method: 'POST',
      body: { email },
      signal,
      auth: false,
    })
    return 60
  } catch (error) {
    throw normalizeAuthError(error)
  }
}

export function normalizeAuthError(error: unknown): Error {
  if (error instanceof DOMException && error.name === 'AbortError') return error
  const body =
    error instanceof HttpError
      ? (error.body as {
          error?: { code?: string; details?: { fields?: { field: string; message: string }[] } }
        } | null)
      : null
  const fields: AuthFieldErrors = {}
  for (const field of body?.error?.details?.fields ?? []) {
    const key = field.field.split('.').at(-1)
    if (key === 'email' || key === 'username') fields.email = field.message
    if (key === 'password') fields.password = field.message
  }
  const retryAfter = error instanceof HttpError ? Number(error.headers.get('Retry-After')) : 0
  return new AuthError(
    apiError(error),
    fields,
    body?.error?.code,
    Number.isFinite(retryAfter) ? Math.max(0, retryAfter) : 0,
  )
}
