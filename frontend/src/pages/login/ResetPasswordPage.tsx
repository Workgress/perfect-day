import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'
import { useMutation } from '@tanstack/react-query'
import { paths } from '@/app/router/paths'
import { announceLogout, expireSession } from '@/app/session'
import { OnboardingPreview } from '@/app/layouts/OnboardingPreview'
import { OnboardingIntro, OnboardingShell } from '@/shared/ui/onboarding/OnboardingShell'
import { Button } from '@/shared/ui/button/Button'
import { FormMessage, TextField } from '@/shared/ui/form-field/FormField'
import { AuthError, resetPassword, validateCredentials } from './auth'
import { RecoveryDialog } from './RecoveryDialog'
import { cooldownLabel, useAuthCooldown } from './useAuthCooldown'
import styles from './AuthForm.module.css'

export function ResetPasswordPage() {
  const navigate = useNavigate()
  const [token, setToken] = useState(
    () => new URLSearchParams(window.location.hash.slice(1)).get('token') ?? '',
  )
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [submitted, setSubmitted] = useState(false)
  const [error, setError] = useState('')
  const [serverPasswordError, setServerPasswordError] = useState('')
  const [invalidToken, setInvalidToken] = useState(!token)
  const [recovery, setRecovery] = useState(false)
  const request = useRef<AbortController | null>(null)
  const passwordRef = useRef<HTMLInputElement>(null)
  const confirmRef = useRef<HTMLInputElement>(null)
  const cooldown = useAuthCooldown()
  const mutation = useMutation({
    mutationFn: (signal: AbortSignal) => resetPassword(token, password, signal),
    retry: false,
    gcTime: 0,
  })
  const errors = validateCredentials(
    { email: 'unused@example.com', password },
    'register',
    confirmation,
  )
  useEffect(() => {
    if (serverPasswordError && !mutation.isPending) passwordRef.current?.focus()
  }, [serverPasswordError, mutation.isPending])
  useEffect(() => {
    window.history.replaceState(
      window.history.state,
      '',
      window.location.pathname + window.location.search,
    )
    return () => request.current?.abort()
  }, [])
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (request.current || !token || invalidToken || cooldown.seconds) return
    setSubmitted(true)
    setError('')
    setServerPasswordError('')
    if (errors.password || errors.confirmPassword) {
      if (errors.password) passwordRef.current?.focus()
      else confirmRef.current?.focus()
      return
    }
    const controller = new AbortController()
    request.current = controller
    try {
      await mutation.mutateAsync(controller.signal)
      if (controller.signal.aborted) return
      setToken('')
      setPassword('')
      setConfirmation('')
      expireSession()
      announceLogout()
      navigate(paths.login, { replace: true, state: { passwordReset: true } })
    } catch (reason) {
      if (controller.signal.aborted) return
      setError(reason instanceof Error ? reason.message : 'Не удалось обновить пароль.')
      if (reason instanceof AuthError) {
        setServerPasswordError(reason.fields.password ?? '')
        if (reason.code === 'INVALID_EMAIL_TOKEN') {
          setInvalidToken(true)
          setToken('')
          setPassword('')
          setConfirmation('')
        }
        if (reason.retryAfter || reason.code === 'RATE_LIMIT_EXCEEDED')
          cooldown.start(reason.retryAfter || 60)
      }
    } finally {
      if (request.current === controller) request.current = null
      mutation.reset()
    }
  }
  return (
    <OnboardingShell step={1} account preview={<OnboardingPreview />}>
      <title>Новый пароль · Идеальный день</title>
      <OnboardingIntro
        title="Задайте новый пароль"
        description="Используйте не меньше 8 символов: буквы и цифры. Не повторяйте старый пароль."
      />
      {error && !invalidToken ? <FormMessage>{error}</FormMessage> : null}
      {invalidToken ? (
        <>
          <FormMessage>
            Ссылка восстановления недействительна или устарела. Запросите новое письмо.
          </FormMessage>
          <Button data-recovery-trigger onClick={() => setRecovery(true)}>
            Получить новую ссылку
          </Button>
        </>
      ) : (
        <form
          className={`${styles.form} ${styles.register}`}
          noValidate
          onSubmit={submit}
          aria-label="Смена пароля"
          aria-busy={mutation.isPending}
        >
          <TextField
            ref={passwordRef}
            label="Новый пароль"
            name="newPassword"
            type="password"
            autoComplete="new-password"
            required
            disabled={mutation.isPending}
            value={password}
            error={serverPasswordError || (submitted ? errors.password : undefined)}
            onChange={(event) => {
              setPassword(event.target.value)
              setServerPasswordError('')
            }}
          />
          <TextField
            ref={confirmRef}
            label="Повторите пароль"
            name="confirmPassword"
            type="password"
            autoComplete="new-password"
            required
            disabled={mutation.isPending}
            value={confirmation}
            error={submitted ? errors.confirmPassword : undefined}
            onChange={(event) => setConfirmation(event.target.value)}
          />
          <Button type="submit" disabled={mutation.isPending || cooldown.seconds > 0}>
            {mutation.isPending
              ? 'Сохраняем…'
              : cooldown.seconds
                ? `Повторить через ${cooldownLabel(cooldown.seconds)}`
                : 'Сохранить и войти'}
          </Button>
        </form>
      )}
      <Link
        className={styles.link}
        to={paths.login}
        aria-disabled={mutation.isPending || undefined}
        onClick={(event) => {
          if (mutation.isPending) event.preventDefault()
        }}
      >
        Вернуться ко входу
      </Link>
      {recovery ? <RecoveryDialog onClose={() => setRecovery(false)} /> : null}
    </OnboardingShell>
  )
}
