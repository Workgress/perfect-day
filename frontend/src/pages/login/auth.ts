import { paths } from '@/app/router/paths'
import type { SessionUser } from '@/stores/session'

export type AuthMode = 'login' | 'register'
export type AuthCredentials = { email: string; password: string }
export type AuthFieldErrors = Partial<Record<keyof AuthCredentials, string>>
export type AuthResult =
  | { status: 'authenticated'; session: { accessToken: string; user: SessionUser } }
  | { status: 'verification_required'; resendAfterSeconds: number }

export class AuthError extends Error {
  readonly fields: AuthFieldErrors

  constructor(message: string, fields: AuthFieldErrors = {}) {
    super(message)
    this.name = 'AuthError'
    this.fields = fields
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
  if (import.meta.env.DEV) {
    const { submitMockAuth } = await import('./auth.mock')
    return submitMockAuth(mode, credentials, signal)
  }
  throw new AuthError('Вход и регистрация пока недоступны. Попробуйте позже.')
}

export async function resendConfirmation(email: string, signal: AbortSignal): Promise<number> {
  if (import.meta.env.DEV) {
    const { resendMockConfirmation } = await import('./auth.mock')
    return resendMockConfirmation(email, signal)
  }
  throw new AuthError('Повторная отправка пока недоступна. Попробуйте позже.')
}
