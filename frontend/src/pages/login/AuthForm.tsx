import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'
import { useMutation } from '@tanstack/react-query'
import { paths } from '@/app/router/paths'
import { announceLogin } from '@/app/session'
import { Button } from '@/shared/ui/button/Button'
import { FormMessage, TextField } from '@/shared/ui/form-field/FormField'
import { ShieldCheckIcon } from '@/shared/ui/icon/icons'
import { useSessionStore } from '@/stores/session'
import {
  AuthError,
  submitAuth,
  validateCredentials,
  type AuthFieldErrors,
  type AuthMode,
} from './auth'
import { RecoveryDialog } from './RecoveryDialog'
import { cooldownLabel, useAuthCooldown } from './useAuthCooldown'
import styles from './AuthForm.module.css'

type Props = { mode: AuthMode; initialEmail: string; redirectTo: string; passwordReset?: boolean }

export function AuthForm({ mode, initialEmail, redirectTo, passwordReset }: Props) {
  const navigate = useNavigate()
  const signIn = useSessionStore((state) => state.signIn)
  const [email, setEmail] = useState(initialEmail)
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [touched, setTouched] = useState({ email: false, password: false, confirmPassword: false })
  const [submitted, setSubmitted] = useState(false)
  const [pending, setPending] = useState(false)
  const [serverErrors, setServerErrors] = useState<AuthFieldErrors>({})
  const [notice, setNotice] = useState<{
    text: string
    tone: 'error' | 'info'
    limited?: boolean
  } | null>(() =>
    passwordReset ? { text: 'Пароль обновлён. Войдите с новым паролем.', tone: 'info' } : null,
  )
  const [recovery, setRecovery] = useState(false)
  const cooldown = useAuthCooldown()
  const emailRef = useRef<HTMLInputElement>(null)
  const passwordRef = useRef<HTMLInputElement>(null)
  const confirmRef = useRef<HTMLInputElement>(null)
  const requestRef = useRef<AbortController | null>(null)
  const isRegister = mode === 'register'
  const mutation = useMutation({
    mutationFn: ({
      credentials,
      signal,
    }: {
      credentials: { email: string; password: string }
      signal: AbortSignal
    }) => submitAuth(mode, credentials, signal),
    retry: false,
    gcTime: 0,
  })
  const errors = validateCredentials(
    { email, password },
    mode,
    isRegister ? confirmation : undefined,
  )
  const error = (field: keyof AuthFieldErrors) =>
    serverErrors[field] ?? (submitted || touched[field] ? errors[field] : undefined)
  useEffect(() => () => requestRef.current?.abort(), [])
  useEffect(() => {
    if (pending) return
    if (serverErrors.email) emailRef.current?.focus()
    else if (serverErrors.password) passwordRef.current?.focus()
  }, [serverErrors, pending])
  const clearNotice = () => {
    if (!cooldown.seconds) setNotice(null)
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (requestRef.current || cooldown.seconds) return
    setSubmitted(true)
    setNotice(null)
    setServerErrors({})
    if (Object.values(errors).some(Boolean)) {
      if (errors.email) emailRef.current?.focus()
      else if (errors.password) passwordRef.current?.focus()
      else confirmRef.current?.focus()
      return
    }
    const controller = new AbortController()
    requestRef.current = controller
    setPending(true)
    try {
      const result = await mutation.mutateAsync({
        credentials: { email: email.trim(), password },
        signal: controller.signal,
      })
      if (controller.signal.aborted) return
      setPassword('')
      setConfirmation('')
      if (result.status === 'authenticated') {
        signIn({ ...result.session, email: email.trim() })
        announceLogin()
        navigate(redirectTo, { replace: true })
      } else
        navigate(paths.verificationSent, {
          replace: true,
          state: {
            email: email.trim(),
            from: redirectTo,
            sent: true,
            resendAfterSeconds: result.resendAfterSeconds,
          },
        })
    } catch (reason) {
      if (controller.signal.aborted) return
      if (reason instanceof AuthError) {
        if (reason.code === 'EMAIL_NOT_VERIFIED') {
          navigate(paths.verificationSent, {
            state: { email: email.trim(), from: redirectTo, sent: false, resendAfterSeconds: 0 },
          })
          return
        }
        setServerErrors(reason.fields)
        const limited = reason.code === 'RATE_LIMIT_EXCEEDED'
        setNotice({
          text:
            reason.code === 'INVALID_CREDENTIALS'
              ? 'Неверная почта или пароль. Проверьте данные.'
              : limited
                ? isRegister
                  ? 'Слишком много попыток регистрации'
                  : 'Слишком много попыток входа'
                : reason.message,
          tone: limited ? 'info' : 'error',
          limited,
        })
        if (limited || reason.retryAfter > 0) cooldown.start(reason.retryAfter || 60)
      } else setNotice({ text: 'Не удалось выполнить запрос. Попробуйте ещё раз.', tone: 'error' })
    } finally {
      if (!controller.signal.aborted) setPending(false)
      if (requestRef.current === controller) requestRef.current = null
      mutation.reset()
    }
  }

  return (
    <>
      {!isRegister ? (
        <>
          <div className={styles.social} aria-label="Вход через другие сервисы">
            {['Google', 'Яндекс ID', 'VK ID'].map((provider) => (
              <Button
                key={provider}
                variant="secondary"
                disabled={pending}
                onClick={() =>
                  setNotice({
                    text: `Вход через ${provider} пока недоступен. Используйте почту.`,
                    tone: 'info',
                  })
                }
              >
                Продолжить с {provider}
              </Button>
            ))}
          </div>
          <div className={`text-caption ${styles.divider}`}>или по почте</div>
        </>
      ) : null}
      <form
        className={`${styles.form} ${isRegister ? styles.register : ''}`}
        noValidate
        aria-label={isRegister ? 'Регистрация по почте' : 'Вход по почте'}
        aria-busy={pending}
        onSubmit={handleSubmit}
      >
        <TextField
          ref={emailRef}
          label="Электронная почта"
          type="email"
          name="email"
          autoComplete="email"
          autoCapitalize="none"
          spellCheck={false}
          required
          disabled={pending}
          value={email}
          error={error('email')}
          onBlur={() => setTouched((value) => ({ ...value, email: true }))}
          onChange={(event) => {
            setEmail(event.target.value)
            setServerErrors((value) => ({ ...value, email: undefined }))
            clearNotice()
          }}
        />
        <TextField
          ref={passwordRef}
          label="Пароль"
          type="password"
          name="password"
          autoComplete={isRegister ? 'new-password' : 'current-password'}
          required
          disabled={pending}
          value={password}
          error={error('password')}
          onBlur={() => setTouched((value) => ({ ...value, password: true }))}
          onChange={(event) => {
            setPassword(event.target.value)
            setServerErrors((value) => ({ ...value, password: undefined }))
            clearNotice()
          }}
        />
        {isRegister ? (
          <>
            <TextField
              ref={confirmRef}
              label="Повторите пароль"
              type="password"
              name="confirmPassword"
              autoComplete="new-password"
              required
              disabled={pending}
              value={confirmation}
              error={error('confirmPassword')}
              onBlur={() => setTouched((value) => ({ ...value, confirmPassword: true }))}
              onChange={(event) => setConfirmation(event.target.value)}
            />
            <p className={styles.secondary}>Не менее 8 символов. Используйте буквы и цифры.</p>
          </>
        ) : null}
        {notice ? (
          <div className={styles.feedback} data-limited={notice.limited || undefined}>
            <FormMessage tone={notice.tone}>{notice.text}</FormMessage>
          </div>
        ) : null}
        {!isRegister ? (
          <div className={`text-caption ${styles.links}`}>
            <button
              type="button"
              data-recovery-trigger
              className={styles.link}
              disabled={pending}
              onClick={() => setRecovery(true)}
            >
              Забыли пароль?
            </button>
            <Link
              className={styles.link}
              to={paths.register}
              state={{ from: redirectTo, email: email.trim() }}
              aria-disabled={pending || undefined}
              onClick={(event) => {
                if (pending) event.preventDefault()
              }}
            >
              Создать аккаунт
            </Link>
          </div>
        ) : null}
        <Button type="submit" disabled={pending || cooldown.seconds > 0}>
          {pending
            ? isRegister
              ? 'Создаём аккаунт…'
              : 'Входим…'
            : cooldown.seconds
              ? `Повторить через ${cooldownLabel(cooldown.seconds)}`
              : isRegister
                ? 'Создать аккаунт'
                : 'Войти'}
        </Button>
        {isRegister ? (
          <div className={`text-caption ${styles.links}`}>
            <Link
              className={styles.link}
              to={paths.login}
              state={{ from: redirectTo, email: email.trim() }}
              aria-disabled={pending || undefined}
              onClick={(event) => {
                if (pending) event.preventDefault()
              }}
            >
              Уже есть аккаунт? Войти
            </Link>
          </div>
        ) : null}
        {pending ? (
          <span className="visually-hidden" role="status">
            {isRegister ? 'Создаём аккаунт' : 'Выполняется вход'}
          </span>
        ) : null}
      </form>
      {isRegister ? (
        <p className={styles.secondary}>
          После регистрации отправим письмо для подтверждения почты.
        </p>
      ) : (
        <p className={`text-caption ${styles.privacy}`}>
          <ShieldCheckIcon size={16} />
          <span>
            Данные передаются в зашифрованном виде. Ваши настройки и задачи доступны только вам.
          </span>
        </p>
      )}
      {recovery ? <RecoveryDialog initialEmail={email} onClose={() => setRecovery(false)} /> : null}
    </>
  )
}
