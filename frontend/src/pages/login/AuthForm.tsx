import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'
import { paths } from '@/app/router/paths'
import { Button } from '@/shared/ui/button/Button'
import { FormMessage, TextField } from '@/shared/ui/form-field/FormField'
import { MailIcon, ShieldCheckIcon } from '@/shared/ui/icon/icons'
import { useSessionStore } from '@/stores/session'
import {
  AuthError,
  resendConfirmation,
  submitAuth,
  validateCredentials,
  type AuthFieldErrors,
  type AuthMode,
} from './auth'
import styles from './AuthForm.module.css'

type AuthFormProps = {
  mode: AuthMode
  initialEmail: string
  redirectTo: string
}

export function AuthForm({ mode, initialEmail, redirectTo }: AuthFormProps) {
  const navigate = useNavigate()
  const signIn = useSessionStore((state) => state.signIn)
  const [email, setEmail] = useState(initialEmail)
  const [password, setPassword] = useState('')
  const [touched, setTouched] = useState({ email: false, password: false })
  const [submitted, setSubmitted] = useState(false)
  const [pending, setPending] = useState(false)
  const [serverErrors, setServerErrors] = useState<AuthFieldErrors>({})
  const [notice, setNotice] = useState<{ text: string; tone: 'error' | 'info' } | null>(null)
  const [verification, setVerification] = useState<{ email: string; resendAt: number } | null>(null)
  const [cooldown, setCooldown] = useState(0)
  const emailRef = useRef<HTMLInputElement>(null)
  const passwordRef = useRef<HTMLInputElement>(null)
  const verificationRef = useRef<HTMLHeadingElement>(null)
  const requestRef = useRef<AbortController | null>(null)
  const isRegister = mode === 'register'
  const errors = validateCredentials({ email, password }, mode)
  const emailError = serverErrors.email ?? (submitted || touched.email ? errors.email : undefined)
  const passwordError =
    serverErrors.password ?? (submitted || touched.password ? errors.password : undefined)

  useEffect(() => () => requestRef.current?.abort(), [])

  useEffect(() => {
    if (pending) return
    if (serverErrors.email) emailRef.current?.focus()
    else if (serverErrors.password) passwordRef.current?.focus()
  }, [serverErrors, pending])

  useEffect(() => {
    if (verification) verificationRef.current?.focus()
  }, [verification])

  useEffect(() => {
    if (!verification || cooldown === 0) return
    const timer = setTimeout(() => {
      setCooldown(Math.max(0, Math.ceil((verification.resendAt - Date.now()) / 1000)))
    }, 1000)
    return () => clearTimeout(timer)
  }, [verification, cooldown])

  const showError = (error: unknown) => {
    if (error instanceof AuthError) {
      setServerErrors(error.fields)
      setNotice({ text: error.message, tone: 'error' })
    } else {
      setNotice({ text: 'Не удалось выполнить запрос. Попробуйте ещё раз.', tone: 'error' })
    }
  }

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (requestRef.current) return
    setSubmitted(true)
    setNotice(null)
    setServerErrors({})
    if (errors.email || errors.password) {
      if (errors.email) emailRef.current?.focus()
      else passwordRef.current?.focus()
      return
    }

    const controller = new AbortController()
    requestRef.current = controller
    setPending(true)
    try {
      const result = await submitAuth(mode, { email: email.trim(), password }, controller.signal)
      if (controller.signal.aborted) return
      setPassword('')
      if (result.status === 'authenticated') {
        signIn(result.session)
        navigate(redirectTo, { replace: true })
      } else {
        setCooldown(result.resendAfterSeconds)
        setVerification({
          email: email.trim(),
          resendAt: Date.now() + result.resendAfterSeconds * 1000,
        })
      }
    } catch (error) {
      if (!controller.signal.aborted) showError(error)
    } finally {
      if (!controller.signal.aborted) setPending(false)
      if (requestRef.current === controller) requestRef.current = null
    }
  }

  const handleResend = async () => {
    if (!verification || cooldown > 0 || requestRef.current) return
    const controller = new AbortController()
    requestRef.current = controller
    setPending(true)
    setNotice(null)
    try {
      const seconds = await resendConfirmation(verification.email, controller.signal)
      if (controller.signal.aborted) return
      setCooldown(seconds)
      setVerification({ ...verification, resendAt: Date.now() + seconds * 1000 })
    } catch (error) {
      if (!controller.signal.aborted) showError(error)
    } finally {
      if (!controller.signal.aborted) setPending(false)
      if (requestRef.current === controller) requestRef.current = null
    }
  }

  if (verification) {
    return (
      <section
        className={styles.verification}
        aria-labelledby="verification-title"
        aria-busy={pending}
      >
        <h2 id="verification-title" className="text-title" tabIndex={-1} ref={verificationRef}>
          Проверьте почту
        </h2>
        <p className={styles.secondary}>
          Ссылка для подтверждения адреса <strong>{verification.email}</strong> позволит продолжить
          настройку.
        </p>
        {import.meta.env.DEV ? (
          <FormMessage tone="info">Демонстрационный режим: письмо не отправляется.</FormMessage>
        ) : null}
        {notice ? <FormMessage tone={notice.tone}>{notice.text}</FormMessage> : null}
        <Button onClick={handleResend} disabled={pending || cooldown > 0}>
          {pending ? 'Отправляем…' : 'Отправить ещё раз'}
        </Button>
        {cooldown > 0 ? (
          <p className={`text-caption ${styles.secondary}`}>
            Повторная отправка через {cooldown} с
          </p>
        ) : null}
        <Link
          className={styles.link}
          to={paths.login}
          state={{ from: redirectTo, email: verification.email }}
        >
          Вернуться ко входу
        </Link>
        <button
          className={styles.link}
          type="button"
          disabled={pending}
          onClick={() => {
            setVerification(null)
            setNotice(null)
            setSubmitted(false)
            setTouched({ email: false, password: false })
          }}
        >
          Исправить адрес
        </button>
      </section>
    )
  }

  return (
    <>
      <div className={styles.social} aria-label="Вход через другие сервисы">
        {['Google', 'Яндекс ID', 'VK ID'].map((provider) => (
          <Button
            key={provider}
            variant="secondary"
            disabled={pending}
            onClick={() => {
              setNotice({
                text: `Вход через ${provider} пока недоступен. Используйте почту.`,
                tone: 'info',
              })
            }}
          >
            Продолжить с {provider}
          </Button>
        ))}
      </div>
      <div className={`text-caption ${styles.divider}`}>или по почте</div>
      <form
        className={styles.form}
        noValidate
        aria-label={isRegister ? 'Регистрация по почте' : 'Вход по почте'}
        aria-busy={pending}
        onSubmit={handleSubmit}
      >
        {notice ? <FormMessage tone={notice.tone}>{notice.text}</FormMessage> : null}
        <TextField
          ref={emailRef}
          label="Email"
          type="email"
          name="email"
          autoComplete="email"
          autoCapitalize="none"
          spellCheck={false}
          required
          disabled={pending}
          value={email}
          error={emailError}
          onBlur={() => setTouched((current) => ({ ...current, email: true }))}
          onChange={(event) => {
            setEmail(event.target.value)
            setServerErrors((current) => ({ ...current, email: undefined }))
            setNotice(null)
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
          error={passwordError}
          hint={isRegister ? 'От 8 до 128 символов' : undefined}
          onBlur={() => setTouched((current) => ({ ...current, password: true }))}
          onChange={(event) => {
            setPassword(event.target.value)
            setServerErrors((current) => ({ ...current, password: undefined }))
            setNotice(null)
          }}
        />
        <div className={`text-caption ${styles.links}`}>
          {isRegister ? (
            <span className={styles.secondary}>Уже есть аккаунт?</span>
          ) : (
            <button
              className={styles.link}
              type="button"
              disabled={pending}
              onClick={() => {
                setNotice({
                  text: 'Восстановление пароля пока недоступно. Попробуйте позже.',
                  tone: 'info',
                })
              }}
            >
              Забыли пароль?
            </button>
          )}
          <Link
            className={styles.link}
            to={isRegister ? paths.login : paths.register}
            state={{ from: redirectTo, email: email.trim() }}
            aria-disabled={pending || undefined}
            onClick={(event) => {
              if (pending) event.preventDefault()
            }}
          >
            {isRegister ? 'Войти' : 'Создать аккаунт'}
          </Link>
        </div>
        <Button type="submit" disabled={pending}>
          <MailIcon />
          {pending
            ? isRegister
              ? 'Создаём аккаунт…'
              : 'Входим…'
            : isRegister
              ? 'Создать аккаунт'
              : 'Войти'}
        </Button>
        {pending ? (
          <span className="visually-hidden" role="status">
            {isRegister ? 'Создаём аккаунт' : 'Выполняется вход'}
          </span>
        ) : null}
      </form>
      <p className={`text-caption ${styles.privacy}`}>
        <ShieldCheckIcon size={16} />
        <span>
          {isRegister
            ? 'Пришлём письмо для подтверждения почты. Данные передаются в зашифрованном виде.'
            : 'Новый аккаунт? Пришлём письмо для подтверждения почты. Данные передаются в зашифрованном виде.'}
        </span>
      </p>
    </>
  )
}
