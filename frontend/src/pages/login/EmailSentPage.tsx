import { useEffect, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router'
import { useMutation } from '@tanstack/react-query'
import { paths } from '@/app/router/paths'
import { OnboardingPreview } from '@/app/layouts/OnboardingPreview'
import { OnboardingIntro, OnboardingShell } from '@/shared/ui/onboarding/OnboardingShell'
import { Button } from '@/shared/ui/button/Button'
import { FormMessage } from '@/shared/ui/form-field/FormField'
import { AuthError, getAuthRedirectPath, resendConfirmation } from './auth'
import { cooldownLabel, useAuthCooldown } from './useAuthCooldown'
import styles from './AuthForm.module.css'

export function EmailSentPage() {
  const { state } = useLocation()
  const data = state as {
    email?: unknown
    sent?: boolean
    from?: unknown
    resendAfterSeconds?: unknown
  } | null
  const email = typeof data?.email === 'string' ? data.email : ''
  const from = getAuthRedirectPath(data?.from)
  const [sent, setSent] = useState(data?.sent === true)
  const [error, setError] = useState('')
  const request = useRef<AbortController | null>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    heading.current?.focus()
  }, [])
  const cooldown = useAuthCooldown(
    typeof data?.resendAfterSeconds === 'number' && Number.isFinite(data.resendAfterSeconds)
      ? Math.min(86400, Math.max(0, data.resendAfterSeconds))
      : 0,
  )
  const mutation = useMutation({
    mutationFn: (signal: AbortSignal) => resendConfirmation(email, signal),
    retry: false,
    gcTime: 0,
  })
  useEffect(() => () => request.current?.abort(), [])
  const resend = async () => {
    if (!email || request.current || cooldown.seconds) return
    const controller = new AbortController()
    request.current = controller
    setError('')
    try {
      const seconds = await mutation.mutateAsync(controller.signal)
      if (!controller.signal.aborted) {
        setSent(true)
        cooldown.start(seconds)
      }
    } catch (reason) {
      if (!controller.signal.aborted) {
        setError(reason instanceof Error ? reason.message : 'Не удалось отправить письмо.')
        if (
          reason instanceof AuthError &&
          (reason.retryAfter || reason.code === 'RATE_LIMIT_EXCEEDED')
        )
          cooldown.start(reason.retryAfter || 60)
      }
    } finally {
      if (request.current === controller) request.current = null
      mutation.reset()
    }
  }
  return (
    <OnboardingShell step={1} account preview={<OnboardingPreview />}>
      <title>Подтвердите почту · Идеальный день</title>
      <OnboardingIntro
        headingRef={heading}
        title="Подтвердите почту"
        description={
          email
            ? sent
              ? `Отправили ссылку на ${email}. Подтвердите адрес в письме. Если письма нет, проверьте папку «Спам».`
              : `Подтвердите адрес ${email}, чтобы продолжить. Запросите новое письмо, если прежняя ссылка недоступна.`
            : 'Вернитесь ко входу или регистрации, чтобы указать адрес почты.'
        }
      />
      {error ? <FormMessage>{error}</FormMessage> : null}
      <Button
        variant="secondary"
        disabled={!email || mutation.isPending || cooldown.seconds > 0}
        onClick={() => void resend()}
      >
        {mutation.isPending ? 'Отправляем…' : 'Отправить письмо ещё раз'}
      </Button>
      {cooldown.seconds > 0 ? (
        <p className={`text-caption ${styles.secondary}`}>
          Повторная отправка через {cooldownLabel(cooldown.seconds)}
        </p>
      ) : null}
      <Link className={styles.link} to={paths.register} state={{ email, from }}>
        Изменить адрес почты
      </Link>
      <Link className={styles.link} to={paths.login} state={{ email, from }}>
        Вернуться ко входу
      </Link>
    </OnboardingShell>
  )
}
