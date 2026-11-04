import { AuthError, type AuthCredentials, type AuthMode, type AuthResult } from './auth'

const DEMO_EMAIL = 'anna@example.com'
const DEMO_PASSWORD = 'demo-password'

async function wait(signal: AbortSignal) {
  signal.throwIfAborted()
  await new Promise<void>((resolve, reject) => {
    const abort = () => {
      clearTimeout(timer)
      reject(new DOMException('Request aborted', 'AbortError'))
    }
    const timer = setTimeout(() => {
      signal.removeEventListener('abort', abort)
      resolve()
    }, 450)
    signal.addEventListener('abort', abort, { once: true })
  })
}

export async function submitMockAuth(
  mode: AuthMode,
  credentials: AuthCredentials,
  signal: AbortSignal,
): Promise<AuthResult> {
  await wait(signal)
  const email = credentials.email.toLowerCase()

  if (mode === 'register') {
    if (email === DEMO_EMAIL) {
      throw new AuthError('Этот адрес уже зарегистрирован. Войдите в аккаунт.', {
        email: 'Этот адрес уже зарегистрирован',
      })
    }
    return { status: 'verification_required', resendAfterSeconds: 60 }
  }

  if (email !== DEMO_EMAIL || credentials.password !== DEMO_PASSWORD) {
    throw new AuthError('Неверный email или пароль. Проверьте данные и попробуйте ещё раз.')
  }

  return {
    status: 'authenticated',
    session: {
      accessToken: 'demo-token',
      user: { name: 'Анна', birthDate: null, chronotype: null },
    },
  }
}

export async function resendMockConfirmation(_email: string, signal: AbortSignal): Promise<number> {
  await wait(signal)
  return 60
}
