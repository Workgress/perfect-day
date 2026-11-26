import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { useMutation } from '@tanstack/react-query'
import { paths } from '@/app/router/paths'
import { announceLogin } from '@/app/session'
import { OnboardingPreview } from '@/app/layouts/OnboardingPreview'
import { requestTokens } from '@/shared/api/auth'
import { Button } from '@/shared/ui/button/Button'
import { FormMessage } from '@/shared/ui/form-field/FormField'
import { OnboardingIntro, OnboardingShell } from '@/shared/ui/onboarding/OnboardingShell'
import { useSessionStore } from '@/stores/session'
import { AuthError, normalizeAuthError } from './auth'
import { cooldownLabel, useAuthCooldown } from './useAuthCooldown'
import styles from './AuthForm.module.css'

export function VerifyEmailPage() {
  const navigate = useNavigate()
  const [token, setToken] = useState(
    () => new URLSearchParams(window.location.hash.slice(1)).get('token') ?? '',
  )
  const [error, setError] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [invalid, setInvalid] = useState(!token)
  const request = useRef<AbortController | null>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    if (confirmed) heading.current?.focus()
  }, [confirmed])
  const cooldown = useAuthCooldown()
  const mutation = useMutation({
    mutationFn: (signal: AbortSignal) => requestTokens('/auth/verify-email', { token }, signal),
    retry: false,
    gcTime: 0,
  })
  useEffect(() => {
    window.history.replaceState(
      window.history.state,
      '',
      window.location.pathname + window.location.search,
    )
    return () => request.current?.abort()
  }, [])
  const confirm = async () => {
    if (!token || request.current || cooldown.seconds) return
    const controller = new AbortController()
    request.current = controller
    setError('')
    try {
      const result = await mutation.mutateAsync(controller.signal)
      if (controller.signal.aborted) return
      setToken('')
      setConfirmed(true)
      useSessionStore
        .getState()
        .signIn({ accessToken: result.access_token, expiresIn: result.expires_in })
      announceLogin()
    } catch (reason) {
      if (controller.signal.aborted) return
      const failure = normalizeAuthError(reason)
      setError(failure.message)
      if (failure instanceof AuthError) {
        if (failure.code === 'INVALID_EMAIL_TOKEN') {
          setInvalid(true)
          setToken('')
        }
        if (failure.retryAfter || failure.code === 'RATE_LIMIT_EXCEEDED')
          cooldown.start(failure.retryAfter || 60)
      }
    } finally {
      if (request.current === controller) request.current = null
      mutation.reset()
    }
  }
  return (
    <OnboardingShell step={1} account preview={<OnboardingPreview />}>
      <title>{confirmed ? 'Почта подтверждена' : 'Подтверждение почты'} · Идеальный день</title>
      <OnboardingIntro
        headingRef={heading}
        title={confirmed ? 'Почта подтверждена' : 'Подтвердите почту'}
        description={
          confirmed
            ? 'Аккаунт готов. Теперь настроим ваш ритм и соберём первое расписание.'
            : 'Нажмите кнопку, чтобы подтвердить адрес и продолжить настройку.'
        }
      />
      {invalid && !error ? (
        <FormMessage>
          В ссылке нет токена подтверждения. Запросите новое письмо на странице входа.
        </FormMessage>
      ) : null}
      {error ? <FormMessage>{error}</FormMessage> : null}
      {confirmed ? (
        <Button onClick={() => navigate(paths.today, { replace: true })}>
          Продолжить настройку
        </Button>
      ) : (
        <>
          <Button
            disabled={!token || invalid || mutation.isPending || cooldown.seconds > 0}
            onClick={() => void confirm()}
          >
            {mutation.isPending
              ? 'Подтверждаем…'
              : cooldown.seconds
                ? `Повторить через ${cooldownLabel(cooldown.seconds)}`
                : 'Подтвердить почту'}
          </Button>
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
        </>
      )}
    </OnboardingShell>
  )
}
